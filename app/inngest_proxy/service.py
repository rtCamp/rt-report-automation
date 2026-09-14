"""Service layer for proxying requests to the Inngest API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.utils import log_and_raise
from app.inngest_proxy.constants import INNGEST_API_BASE_URL, INNGEST_API_TIMEOUT
from app.inngest_proxy.errors import (
	CANCELLED_STATUSES,
	FAILED_STATUSES,
	RunErrorCode,
	classify_failure,
	collapse_repeated_sentence,
	drive_folder_url,
	extract_drive_folder_id,
	extract_failure_text,
	truncate_detail,
)
from app.inngest_proxy.models import RunErrorDetail, RunStatus, RunStatusResponse

logger = logging.getLogger(__name__)

# Error codes that only engineering can act on -- everything else in the
# rule table is something the PM can fix themselves.
_NOT_USER_FIXABLE = frozenset(
	{
		RunErrorCode.UNKNOWN,
		RunErrorCode.TEMPLATE_MISMATCH,
		RunErrorCode.NO_DOCUMENT_PRODUCED,
		RunErrorCode.GOOGLE_AUTH_FAILED,
	},
)

_STATE_MESSAGES = {
	RunStatus.PENDING: "Report generation is queued…",
	RunStatus.RUNNING: "Report generation is in progress…",
	RunStatus.COMPLETED: "Report generated successfully.",
}


class InngestProxyService:
	"""Service for proxying status requests to the Inngest REST API."""

	def __init__(self):
		"""Initialize the InngestProxyService."""
		self.signing_key = settings.INNGEST_SIGNING_KEY.get_secret_value()

	async def get_run_status(self, event_id: str) -> RunStatusResponse:
		"""Fetch and normalize the run status for a given event ID.

		Args:
			event_id (str): The Inngest event ID to look up.

		Returns:
			RunStatusResponse: Normalized status with a toast-ready message and,
				on failure, structured error detail.

		Raises:
			HTTPException: If the Inngest API returns an error or is unreachable.

		"""
		payload = await self._fetch_runs(event_id)
		runs = payload.get("data") or []
		run = self._select_run(runs)

		if run is None:
			# Inngest has accepted the event but not yet materialized a run.
			return RunStatusResponse(
				event_id=event_id,
				status=RunStatus.PENDING,
				is_terminal=False,
				message="Waiting for the run to start…",
			)

		return self._build_response(event_id, run)

	@staticmethod
	def _select_run(runs: Any) -> dict | None:
		"""Pick the live run for an event.

		List order isn't guaranteed, and `retries` leaves earlier attempts
		alongside the current one, so the newest start wins.
		"""
		if not isinstance(runs, list):
			return None

		candidates = [r for r in runs if isinstance(r, dict)]
		if not candidates:
			return None

		return max(candidates, key=lambda r: str(r.get("run_started_at") or ""))

	async def _fetch_runs(self, event_id: str) -> dict[str, Any]:
		"""Fetch the raw runs payload for an event from the Inngest API."""
		url = f"{INNGEST_API_BASE_URL}/events/{event_id}/runs"

		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					url,
					headers={"Authorization": f"Bearer {self.signing_key}"},
					timeout=INNGEST_API_TIMEOUT,
				)
				response.raise_for_status()
				return response.json()
		except httpx.HTTPStatusError as exc:
			log_and_raise(
				logger,
				f"Inngest API returned HTTP {exc.response.status_code}",
				http_status_code=502,
				cause=exc,
			)
		except Exception as exc:
			log_and_raise(
				logger,
				"Failed to check run status from Inngest",
				http_status_code=502,
				cause=exc,
			)

	def _build_response(self, event_id: str, run: dict) -> RunStatusResponse:
		"""Normalize a single Inngest run record into the frontend response."""
		run_id = run.get("run_id")
		output = run.get("output")
		status = self._derive_state(run.get("status"))

		document_url = None
		error = None

		if status is RunStatus.COMPLETED:
			document_url = (
				output.get("document_url") if isinstance(output, dict) else None
			)
			if not run.get("ended_at"):
				# Inngest reports "Completed" before the run has actually
				# finished -- `ended_at` and `output` are still null. Treat
				# that as in-flight so a mid-run poll doesn't declare either
				# success or failure prematurely.
				status = RunStatus.RUNNING
				document_url = None
			elif not document_url:
				# A genuinely finished run with no URL is a real failure from
				# the user's point of view -- report it as one instead of
				# leaving the frontend to guess.
				status = RunStatus.FAILED
				error = self._build_error(
					run,
					code=RunErrorCode.NO_DOCUMENT_PRODUCED,
					user_message=(
						"Report generation finished but no document was produced."
					),
					action=None,
				)
		elif status is RunStatus.CANCELLED:
			error = self._build_error(
				run,
				code=RunErrorCode.RUN_CANCELLED,
				user_message="Report generation was cancelled before it finished.",
				action="Trigger the report again.",
			)
		elif status is RunStatus.FAILED:
			code, user_message, action = classify_failure(output)
			error = self._build_error(
				run,
				code=code,
				user_message=user_message,
				action=action,
			)

		return RunStatusResponse(
			event_id=event_id,
			run_id=run_id,
			function_id=run.get("function_id"),
			status=status,
			is_terminal=status
			in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED},
			message=self._build_message(status, error),
			document_url=document_url,
			error=error,
			started_at=run.get("run_started_at"),
			ended_at=run.get("ended_at"),
			raw=run,
		)

	@staticmethod
	def _derive_state(status: str | None) -> RunStatus:
		"""Map Inngest's raw status string onto a coarse run status."""
		if status in FAILED_STATUSES:
			return RunStatus.FAILED
		if status in CANCELLED_STATUSES:
			return RunStatus.CANCELLED
		if status == "Completed":
			return RunStatus.COMPLETED
		if status == "Running":
			return RunStatus.RUNNING
		return RunStatus.PENDING

	@staticmethod
	def _build_error(
		run: dict,
		code: RunErrorCode,
		user_message: str,
		action: str | None,
	) -> RunErrorDetail:
		"""Assemble the structured error detail for a terminal failed run."""
		# The run ID is the trace ID: it is what engineering searches Inngest
		# and the application logs by, and it is stable across polls so the
		# value the user copies stays valid.
		trace_id = run.get("run_id") or run.get("event_id") or "unavailable"

		# Stack traces help classification but are noise in a user-facing
		# payload -- the full trace stays available under `raw`.
		raw_text = extract_failure_text(run.get("output"), include_stack=False)
		match_text = extract_failure_text(run.get("output"))

		# When the failure names a Drive folder, hand the user a direct link to
		# it -- the fix ("create a subfolder here") is a click away, and a bare
		# folder ID in a log line is not something a PM can act on.
		folder_id = extract_drive_folder_id(match_text)

		return RunErrorDetail(
			error_code=code,
			user_message=user_message,
			action=action,
			is_user_fixable=code not in _NOT_USER_FIXABLE,
			technical_detail=truncate_detail(collapse_repeated_sentence(raw_text)),
			resource_url=drive_folder_url(folder_id) if folder_id else None,
			trace_id=str(trace_id),
			occurred_at=run.get("ended_at"),
		)

	@staticmethod
	def _build_message(status: RunStatus, error: RunErrorDetail | None) -> str:
		"""Build the single status line the toast renders."""
		if error is not None:
			if error.action:
				return f"{error.user_message} {error.action}"
			return error.user_message

		return _STATE_MESSAGES.get(status, "Report generation is in progress…")
