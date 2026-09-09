"""Classification of Inngest run failures into user-facing error details."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from functools import lru_cache
from typing import Any, NamedTuple

from app.core.config import settings
from app.google_docs.utils.constants import AUTOMATED_DOCS_FOLDER_NAME


class RunErrorCode(StrEnum):
	"""Stable error codes the frontend can branch on."""

	INVALID_DATE_RANGE = "invalid_date_range"
	NO_DATA_FOR_FILTERS = "no_data_for_filters"
	SLACK_CHANNEL_NOT_FOUND = "slack_channel_not_found"
	SLACK_ACCESS_DENIED = "slack_access_denied"
	GITHUB_ACCESS_DENIED = "github_access_denied"
	GOOGLE_DRIVE_PERMISSION = "google_drive_permission"
	AUTOMATED_DOCS_FOLDER_MISSING = "automated_docs_folder_missing"
	DRIVE_FOLDER_NOT_SHARED = "drive_folder_not_shared"
	DRIVE_STORAGE_FULL = "drive_storage_full"
	GOOGLE_AUTH_FAILED = "google_auth_failed"
	INVALID_DRIVE_LINK = "invalid_drive_link"
	TEMPLATE_MISMATCH = "template_mismatch"
	MISSING_PROJECT_FIELD = "missing_project_field"
	INVALID_INPUT = "invalid_input"
	LLM_RATE_LIMITED = "llm_rate_limited"
	LLM_UNAVAILABLE = "llm_unavailable"
	CONTENT_TOO_LARGE = "content_too_large"
	UPSTREAM_TIMEOUT = "upstream_timeout"
	RUN_CANCELLED = "run_cancelled"
	NO_DOCUMENT_PRODUCED = "no_document_produced"
	UNKNOWN = "unknown"


class ErrorRule(NamedTuple):
	"""A single classification rule.

	Attributes:
		code: The stable error code assigned on a match.
		pattern: Case-insensitive regex matched against the raw failure text.
		user_message: Plain-language explanation shown in the toast/status.
		action: Optional next step for the user, when the cause is user-fixable.

	"""

	code: RunErrorCode
	pattern: re.Pattern[str]
	user_message: str
	action: str | None = None


def _rule(
	code: RunErrorCode,
	pattern: str,
	user_message: str,
	action: str | None = None,
) -> ErrorRule:
	"""Build an ErrorRule with a compiled, case-insensitive pattern."""
	return ErrorRule(code, re.compile(pattern, re.IGNORECASE), user_message, action)


@lru_cache(maxsize=1)
def get_service_account_email() -> str | None:
	"""Return the service account address, or None if it can't be read.

	Drive fixes ("share the folder with...") are only actionable if the message
	names the address to share with, so it is resolved from the configured
	service account key rather than left for the PM to hunt down.
	"""
	try:
		info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_KEY.get_secret_value())
	except (json.JSONDecodeError, AttributeError, ValueError):
		return None

	email = info.get("client_email") if isinstance(info, dict) else None
	return str(email) if email else None


def _render_action(action: str | None) -> str | None:
	"""Fill placeholders in a rule's action text with live configuration."""
	if not action:
		return action

	if "{service_account}" in action:
		email = get_service_account_email()
		# Without the address, naming it is worse than describing it generally.
		action = action.replace(
			"{service_account}",
			email or "the report bot's service account",
		)

	return action.replace("{automated_docs_folder}", AUTOMATED_DOCS_FOLDER_NAME)


# Drive folder IDs as they appear in our own error text, e.g.
# "... not found in parent folder 1cXu0Turb42LYKqyskt-p_hE-RozsqDCs or its ..."
_DRIVE_FOLDER_ID_PATTERN = re.compile(
	r"(?:parent folder|folder id|file not found:)\s+([A-Za-z0-9_-]{15,})",
	re.IGNORECASE,
)


def extract_drive_folder_id(text: str) -> str | None:
	"""Pull the Drive folder ID out of a failure message, if it names one."""
	match = _DRIVE_FOLDER_ID_PATTERN.search(text)
	return match.group(1) if match else None


def drive_folder_url(folder_id: str) -> str:
	"""Build the Drive URL for a folder ID, so the user can open it directly."""
	return f"https://drive.google.com/drive/folders/{folder_id}"


# Ordered most-specific first -- the first matching rule wins, so a narrow
# cause (e.g. "channel_not_found") is not swallowed by a broader one
# (e.g. a generic Slack API error).
ERROR_RULES: tuple[ErrorRule, ...] = (
	_rule(
		RunErrorCode.INVALID_DATE_RANGE,
		r"start_date must be less than or equal to end_date|invalid date range",
		"The selected date range is invalid.",
		"Pick a start date on or before the end date, then try again.",
	),
	_rule(
		RunErrorCode.SLACK_CHANNEL_NOT_FOUND,
		r"channel_not_found|no channel (was )?found|channel .* not found",
		"The Slack channel for this project could not be found.",
		"Check the channel slug on the project in PMS, then try again.",
	),
	_rule(
		RunErrorCode.SLACK_ACCESS_DENIED,
		r"not_in_channel|missing_scope|invalid_auth|account_inactive|token_revoked",
		"The report bot does not have access to the Slack channel.",
		"Invite the bot to the channel, then try again.",
	),
	_rule(
		RunErrorCode.NO_DATA_FOR_FILTERS,
		r"no standup|no messages|no data (found|available)|empty (result|data)",
		"No standup data was found for the selected project and date range.",
		"Widen the date range or confirm standups were posted, then try again.",
	),
	_rule(
		RunErrorCode.GITHUB_ACCESS_DENIED,
		r"github.*(401|403|bad credentials|not accessible|installation)"
		r"|failed to get installation token|failed to generate jwt",
		"GitHub data could not be fetched for this project.",
		"Confirm the repository is correct and the GitHub App is installed on it.",
	),
	_rule(
		RunErrorCode.INVALID_DRIVE_LINK,
		r"invalid google drive folder link|drive link cannot be empty"
		r"|invalid google docs url",
		"The project's Google Drive link is missing or malformed.",
		"Fix the drive link on the project in PMS, then try again.",
	),
	_rule(
		RunErrorCode.AUTOMATED_DOCS_FOLDER_MISSING,
		r"folder '?automated docs'? not found|please create the folder manually",
		(
			"The project's Drive folder has no '{automated_docs_folder}' subfolder, "
			"which is where generated reports are filed."
		),
		(
			"Create a folder named '{automated_docs_folder}' inside the project's "
			"Drive folder, then try again."
		),
	),
	_rule(
		RunErrorCode.DRIVE_STORAGE_FULL,
		r"storagequotaexceeded|quota.*storage|drive storage",
		"The report bot's Google Drive storage is full.",
	),
	_rule(
		RunErrorCode.GOOGLE_AUTH_FAILED,
		r"failed to refresh service account credentials"
		r"|invalid_grant|invalid jwt|service account key",
		"The report bot could not authenticate with Google.",
	),
	_rule(
		RunErrorCode.DRIVE_FOLDER_NOT_SHARED,
		# A 404 from Drive on a folder we were handed almost always means "not
		# shared with us" rather than "deleted" -- Drive hides what the caller
		# cannot see, so this is reported as a sharing problem.
		r"file not found: |notfound.*folder|folder not found|access denied"
		r"|does not have permission|the user does not have sufficient permissions",
		"The report bot cannot see the project's Google Drive folder.",
		(
			"Share the project's Drive folder with {service_account} as an Editor, "
			"then try again."
		),
	),
	_rule(
		RunErrorCode.GOOGLE_DRIVE_PERMISSION,
		r"check folder permissions|check document permissions"
		r"|insufficient permission|permission denied|forbidden|403",
		"The report bot cannot write to the project's Google Drive folder.",
		("Share the folder with {service_account} as an Editor, then try again."),
	),
	_rule(
		RunErrorCode.TEMPLATE_MISMATCH,
		r"check template tags|hours breakdown table shape mismatch"
		r"|no document id returned",
		"The Google Docs template does not match what the report expects.",
	),
	_rule(
		RunErrorCode.MISSING_PROJECT_FIELD,
		r"missing required field",
		"A required project field is missing.",
		"Fill in the missing field on the project in PMS, then try again.",
	),
	_rule(
		RunErrorCode.CONTENT_TOO_LARGE,
		r"context (length|window)|too many tokens|maximum context|request too large",
		"There was too much data in the selected range to summarize in one report.",
		"Narrow the date range, then try again.",
	),
	_rule(
		RunErrorCode.LLM_RATE_LIMITED,
		r"rate limit|429|too many requests|quota exceeded|throttl",
		"The AI provider is rate limiting requests right now.",
		"Wait a few minutes, then try again.",
	),
	_rule(
		RunErrorCode.LLM_UNAVAILABLE,
		r"overloaded|service unavailable|503|502|api (error|connection error)"
		r"|upstream (error|connect)",
		"The AI provider is temporarily unavailable.",
		"Wait a few minutes, then try again.",
	),
	_rule(
		RunErrorCode.UPSTREAM_TIMEOUT,
		r"timeout|timed out|deadline exceeded",
		"A step in report generation timed out.",
		"Try again; if it keeps failing, narrow the date range.",
	),
	_rule(
		RunErrorCode.INVALID_INPUT,
		r"validation error|invalid model metadata|cannot be empty"
		r"|expected \w+ for|invalid input",
		"Some of the submitted report details were invalid.",
		"Review the form values, then try again.",
	),
)

GENERIC_USER_MESSAGE = (
	"Report generation failed for an unexpected reason. "
	"Share the trace ID with engineering so they can check the logs."
)

# Terminal states Inngest reports for a run that will not produce a document.
FAILED_STATUSES = frozenset({"Failed"})
CANCELLED_STATUSES = frozenset({"Cancelled"})

# Cap on how much raw failure text is echoed back, so a multi-thousand-line
# stack trace can't bloat every poll response.
MAX_TECHNICAL_DETAIL_CHARS = 2000


def extract_failure_text(output: Any) -> str:
	"""Flatten an Inngest run `output` into searchable text.

	Inngest reports a failure as an object with `name`, `message` and `stack`
	keys, but a function that raised something unusual can leave a bare string
	or an arbitrary dict there, so every shape is handled.

	Args:
		output: The `output` value from an Inngest run record.

	Returns:
		str: Text suitable for pattern matching, empty if nothing usable.

	"""
	if output is None:
		return ""

	if isinstance(output, str):
		return output

	if isinstance(output, dict):
		parts = [
			str(output[key])
			for key in ("name", "code", "message", "error", "detail", "stack")
			if output.get(key)
		]
		return "\n".join(dedupe_repeated_text(parts)) if parts else str(output)

	return str(output)


def dedupe_repeated_text(parts: list[str]) -> list[str]:
	"""Drop parts already contained in an earlier part.

	`log_and_raise(..., cause=e)` appends the cause's text to its own message,
	so by the time a failure surfaces in Inngest the same sentence can appear
	two or three times over ("Failed to generate Google Doc: X: X"). Keeping
	every copy makes `technical_detail` hard to read for no added information.
	"""
	kept: list[str] = []
	for part in parts:
		stripped = part.strip()
		if not stripped or any(stripped in seen for seen in kept):
			continue
		# A new part that subsumes an earlier one replaces it.
		kept = [seen for seen in kept if seen not in stripped]
		kept.append(stripped)
	return kept


def collapse_repeated_sentence(text: str) -> str:
	"""Collapse a message that repeats the same trailing sentence.

	`log_and_raise(..., cause=e)` builds its message as "context: {cause}", so
	when the cause's own message is already the full sentence the result reads
	"Failed to generate Google Doc: X: X". Only the final copy carries new
	information; the duplicates are noise in `technical_detail`.
	"""
	collapsed_lines = []

	for line in text.splitlines():
		# Repeatedly strip a trailing ": X" whose X already ends the head.
		current = line.strip()
		while True:
			head, found, tail = current.rpartition(": ")
			tail = tail.strip()
			if not found or not tail or not head.strip().endswith(tail):
				break
			current = head.strip()
		collapsed_lines.append(current)

	return "\n".join(collapsed_lines)


def classify_failure(output: Any) -> tuple[RunErrorCode, str, str | None]:
	"""Map a failed run's output onto a user-facing error code and message.

	Args:
		output: The `output` value from a failed Inngest run record.

	Returns:
		tuple[RunErrorCode, str, str | None]: The error code, the plain-language
			user message, and a suggested user action (None when the cause is
			not user-fixable).

	"""
	text = extract_failure_text(output)

	for rule in ERROR_RULES:
		if rule.pattern.search(text):
			return (
				rule.code,
				_render_action(rule.user_message) or rule.user_message,
				_render_action(rule.action),
			)

	return RunErrorCode.UNKNOWN, GENERIC_USER_MESSAGE, None


def truncate_detail(text: str) -> str | None:
	"""Trim raw failure text to a bounded, single-line-safe detail string."""
	cleaned = text.strip()
	if not cleaned:
		return None

	if len(cleaned) <= MAX_TECHNICAL_DETAIL_CHARS:
		return cleaned

	return f"{cleaned[:MAX_TECHNICAL_DETAIL_CHARS]}… (truncated)"
