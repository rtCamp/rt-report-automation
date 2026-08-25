"""Controller for the Slack /pms slash command and the PMS bulk audit trigger."""

import datetime

import inngest
from fastapi import APIRouter, Depends, Request, Response
from fastapi.logger import logger

from app.core.adapters import inngest_client
from app.slack.auth import verify_slack_signature

router = APIRouter(
	prefix="/slack",
	tags=["Slack Commands"],
	dependencies=[Depends(verify_slack_signature)],
)

# Separate router (not `router` above): this is pinged by Frappe's scheduler,
# not Slack, so it needs `X-API-KEY` auth (applied where this is registered
# in app/core/api.py) rather than Slack signature verification.
audit_router = APIRouter(
	prefix="/audit",
	tags=["PMS Bulk Audit"],
)

_SUBCOMMANDS = {"projects", "missing-fields", "audit"}
_USAGE_TEXT = (
	"Usage: `/pms projects`, `/pms missing-fields`, or `/pms audit <PROJECT-ID>`. "
	"`missing-fields` can optionally take a project name or ID to filter to a "
	"single project, e.g. `/pms missing-fields PROJ-0669`. `audit` requires one, "
	"e.g. `/pms audit PROJ-0669`."
)
_AUDIT_USAGE_TEXT = "Usage: `/pms audit <PROJECT-ID>`, e.g. `/pms audit PROJ-0669`."


@router.post(
	"/commands",
	summary="Slack /pms slash command",
	description="Receives the /pms slash command and dispatches it asynchronously.",
)
async def handle_slash_command(request: Request):
	"""Handle an incoming Slack slash command.

	Immediately acknowledges within Slack's 3-second window, then dispatches
	the actual Frappe lookup to an Inngest function that replies via the
	command's `response_url`. For `audit`, the immediate ack is a visible
	"generating..." message; since Slack replaces a response_url message's
	content by default on each subsequent post, the Inngest function's
	final report (also posted to `response_url`) replaces it in place
	rather than appearing as a second message. Other subcommands ack
	silently (empty 200, no visible message) since they're fast enough
	not to need a loading indicator.
	"""
	form = await request.form()
	user_id = str(form.get("user_id", ""))
	response_url = str(form.get("response_url", ""))
	raw_text = str(form.get("text", "")).strip()

	parts = raw_text.split(maxsplit=1)
	subcommand = parts[0].lower() if parts else ""
	project_filter = parts[1].strip() if len(parts) > 1 else None

	if subcommand not in _SUBCOMMANDS:
		return {"response_type": "in_channel", "text": _USAGE_TEXT}

	if subcommand == "audit" and not project_filter:
		return {"response_type": "in_channel", "text": _AUDIT_USAGE_TEXT}

	try:
		await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/pms_command",
				data={
					"user_id": user_id,
					"subcommand": subcommand,
					"project_filter": project_filter,
					"response_url": response_url,
				},
			),
		)
	except Exception as e:
		logger.error(f"Error sending pms_command event to Inngest: {e}")
		return {
			"response_type": "in_channel",
			"text": "Something went wrong queuing your request. Please try again.",
		}

	if subcommand == "audit":
		return {
			"response_type": "in_channel",
			"text": f"⏳ Generating audit for `{project_filter}`...",
		}

	return Response(status_code=200)


@audit_router.post(
	"/run-all",
	summary="Trigger a bulk audit of all open, billable projects",
	description=(
		"Meant to be pinged by Frappe's scheduler. Acknowledges immediately and "
		"queues the actual audit-and-DM work to an Inngest function -- this "
		"endpoint's only job is to send the ping onward. Pass `project_id` to "
		"scope the run to a single project, and/or `dry_run=true` to preview "
		"which projects would be audited without sending anything. Duplicate "
		"full runs (same project scope, same UTC day) are deduped so a "
		"scheduler retry or an overlapping manual trigger doesn't double-DM "
		"every project manager."
	),
)
async def trigger_bulk_audit(project_id: str | None = None, *, dry_run: bool = False):
	"""Queue a run of `run_all_project_audits` and acknowledge immediately."""
	today = datetime.datetime.now(datetime.UTC).date()
	try:
		await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/run_all_project_audits",
				# Deterministic per (day, scope)
				id=f"run-all-{today}-{project_id or 'all'}-{dry_run}",
				data={"project_id": project_id, "dry_run": dry_run},
			),
		)
	except Exception as e:
		logger.error(f"Error sending run_all_project_audits event to Inngest: {e}")
		return Response(status_code=502)

	return Response(status_code=200)
