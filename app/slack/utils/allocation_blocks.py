"""Block Kit formatting for the allocation reminder and extension flow."""

import datetime as dt
import json

from app.core.config import settings
from app.slack.constants import (
	ALLOCATION_DAYS_ACTION_ID,
	ALLOCATION_DAYS_BLOCK_ID,
	ALLOCATION_DECLINE_ACTION_ID,
	ALLOCATION_EXTEND_ACTION_ID,
	ALLOCATION_EXTEND_CALLBACK_ID,
	ALLOCATION_EXTEND_MAX_DAYS,
	ALLOCATION_VIEW_PROJECT_ACTION_ID,
)
from app.slack.utils.helpers import _link_button, _project_overview_url


def _format_date(day: dt.date) -> str:
	"""Format a date as e.g. "1 Oct 2026"."""
	return f"{day.day} {day:%b %Y}"


def _format_date_range(start: dt.date, end: dt.date) -> str:
	"""Format a date range as e.g. "2 Oct–31 Oct 2026"."""
	if start.year == end.year:
		return f"{start.day} {start:%b}–{_format_date(end)}"
	return f"{_format_date(start)}–{_format_date(end)}"


def allocation_erp_url(name: str) -> str:
	"""Build a link to the allocation's form in ERP."""
	base = str(settings.FRAPPE_BASE_URL).rstrip("/")
	return f"{base}/app/resource-allocation/{name}"


def allocation_context(allocation: dict, sent_on: dt.date) -> dict:
	"""Build the allocation context carried through Slack from an ERP record."""
	return {
		"name": allocation["name"],
		"project": allocation["project"],
		"employee_name": allocation.get("employee_name") or allocation["employee"],
		"project_name": allocation.get("project_name") or allocation["project"],
		"end": str(allocation["allocation_end_date"]),
		"hours": float(allocation.get("hours_allocated_per_day") or 0),
		# ERP revision the PM saw; the extension is refused if it changed.
		"modified": str(allocation["modified"]),
		"sent_on": sent_on.isoformat(),
	}


def extension_dates(end: dt.date, days: int) -> tuple[dt.date, dt.date]:
	"""Return (first day, new end date) for extending an allocation by `days`."""
	return end + dt.timedelta(days=1), end + dt.timedelta(days=days)


def parse_extension_days(raw: object) -> int | None:
	"""Parse the days input, or None unless it's a whole number in range."""
	try:
		days = int(str(raw).strip())
	except (TypeError, ValueError):
		return None
	return days if 1 <= days <= ALLOCATION_EXTEND_MAX_DAYS else None


def _header(text: str) -> dict:
	"""Build a header block."""
	return {
		"type": "header",
		"text": {"type": "plain_text", "text": text, "emoji": True},
	}


def _reminder_header(ctx: dict) -> dict:
	"""Build the reminder's header, numbered when the manager got several that day."""
	position = ctx.get("position")
	return _header(
		f"Allocation ending soon · {position}" if position else "Allocation ending soon"
	)


# Ends every allocation message, so consecutive DMs read as separate cards.
_DIVIDER = {"type": "divider"}


def _section(text: str) -> dict:
	"""Build a mrkdwn section block."""
	return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict:
	"""Build a mrkdwn context block."""
	return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _reminder_details(ctx: dict) -> str:
	"""Build the reminder's member/project/end date/hours lines."""
	end = dt.date.fromisoformat(ctx["end"])
	return (
		f"*Member:* {ctx['employee_name']}\n"
		f"*Project:* {ctx['project_name']}\n"
		f"*Current end date:* {_format_date(end)}\n"
		f"*Hours per day:* {ctx['hours']:g}"
	)


def _reminder_question(ctx: dict) -> str:
	"""Build the reminder's question."""
	return (
		f"Would you like to extend {ctx['employee_name']} on "
		f"{ctx['project_name']} at {ctx['hours']:g} hours per day?"
	)


def _project_button(ctx: dict) -> list[dict]:
	"""Build the "View project in Next PMS" button."""
	return [
		{
			"type": "button",
			"text": {"type": "plain_text", "text": "View project in Next PMS"},
			"url": _project_overview_url(ctx["project"]),
			"action_id": ALLOCATION_VIEW_PROJECT_ACTION_ID,
		},
	]


def _reminder_actions(ctx: dict) -> dict:
	"""Build the reminder's Yes/No buttons and Next PMS project link."""
	value = json.dumps(ctx, separators=(",", ":"))
	elements = [
		{
			"type": "button",
			"text": {"type": "plain_text", "text": "Yes, extend"},
			"style": "primary",
			"action_id": ALLOCATION_EXTEND_ACTION_ID,
			"value": value,
		},
		{
			"type": "button",
			"text": {"type": "plain_text", "text": "No"},
			"action_id": ALLOCATION_DECLINE_ACTION_ID,
			"value": value,
		},
		*_project_button(ctx),
	]
	return {"type": "actions", "elements": elements}


def _reminder_footer(ctx: dict) -> str:
	"""Say how soon the allocation ends and when the reminders stop."""
	days_left = (
		dt.date.fromisoformat(ctx["end"]) - dt.date.fromisoformat(ctx["sent_on"])
	).days
	ends = (
		"Ends today"
		if days_left == 0
		else f"Ends in {days_left} day{'s' if days_left != 1 else ''}"
	)
	return (
		f"{ends}. You'll be reminded each weekday until it's extended or "
		f"{ctx['employee_name']} is fully booked elsewhere."
	)


def format_allocation_reminder(ctx: dict) -> tuple[str, list[dict]]:
	"""Build the allocation-ending reminder with Yes/No buttons."""
	blocks = [
		_reminder_header(ctx),
		_section(_reminder_details(ctx)),
		_section(_reminder_question(ctx)),
		_reminder_actions(ctx),
		_context(_reminder_footer(ctx)),
		_DIVIDER,
	]
	return f"Allocation ending soon: {_reminder_question(ctx)}", blocks


def format_reminder_outcome(
	ctx: dict,
	outcome: str,
	*,
	retry: bool = False,
) -> tuple[str, list[dict]]:
	"""Replace the reminder's question and buttons with an outcome line."""
	blocks = [
		_reminder_header(ctx),
		_section(_reminder_details(ctx)),
		_section(outcome),
	]
	if retry:
		blocks.append(_reminder_actions(ctx))
	elif project_button := _project_button(ctx):
		blocks.append({"type": "actions", "elements": project_button})
	blocks.append(_DIVIDER)
	return outcome, blocks


def format_extension_success(
	ctx: dict,
	new_end: dt.date,
	hours: float,
	days: int,
) -> tuple[str, list[dict]]:
	"""Build the confirmation shown once ERP has saved the extension."""
	start = dt.date.fromisoformat(ctx["end"]) + dt.timedelta(days=1)
	summary = f"{ctx['employee_name']} will continue on {ctx['project_name']}."
	blocks = [
		_header("✅ Allocation extended"),
		_section(summary),
		_section(
			f"> *Extension:* {_format_date_range(start, new_end)}\n"
			f"> *Hours per day:* {hours:g}\n"
			f"> *Duration:* {days} calendar days\n"
			f"> *New allocation end date:* {_format_date(new_end)}",
		),
		{
			"type": "actions",
			"elements": [
				*_link_button(
					"View allocation in ERP",
					allocation_erp_url(ctx["name"]),
					"view_allocation_in_erp",
				)["elements"],
				*_project_button(ctx),
			],
		},
		_context("The existing allocation has been updated."),
		_DIVIDER,
	]
	return f"✅ Allocation extended. {summary}", blocks


def format_reminder_superseded(ctx: dict) -> tuple[str, list[dict]]:
	"""Close a reminder that a newer one for the same allocation replaces."""
	return format_reminder_outcome(ctx, "↪️ Replaced by a newer reminder.")


SUPERSEDED_MESSAGE = (
	"↪️ This reminder was replaced by a newer one. Use the latest reminder for "
	"this allocation."
)


def format_allocation_changed(
	ctx: dict,
	latest: dict,
	consequence: str = "it wasn't extended",
) -> str:
	"""Explain that the allocation changed since the reminder, with its latest state."""
	end = dt.date.fromisoformat(str(latest["allocation_end_date"]))
	hours = float(latest.get("hours_allocated_per_day") or 0)
	return (
		f"⚠️ This allocation was changed after this reminder was sent, so "
		f"{consequence}. It now ends on *{_format_date(end)}* at "
		f"*{hours:g} hours per day*. "
		f"<{allocation_erp_url(ctx['name'])}|View it in ERP>."
	)


def _extension_preview(ctx: dict, days_raw: str | None) -> str:
	"""Build the modal's preview text for the days typed so far."""
	if not days_raw:
		return "_Enter the number of days to preview the extension._"

	days = parse_extension_days(days_raw)
	if days is None:
		return f"⚠️ Enter a whole number of days from 1 to {ALLOCATION_EXTEND_MAX_DAYS}."

	start, new_end = extension_dates(dt.date.fromisoformat(ctx["end"]), days)
	return (
		"*Extension preview*\n"
		f"From: {_format_date(start)}\n"
		f"To: {_format_date(new_end)}\n"
		f"Hours per day: {ctx['hours']:g}"
	)


def build_extend_modal(ctx: dict, days_raw: str | None = None) -> dict:
	"""Build the duration modal, with a preview for `days_raw` if given."""
	end = dt.date.fromisoformat(ctx["end"])
	return {
		"type": "modal",
		"callback_id": ALLOCATION_EXTEND_CALLBACK_ID,
		"private_metadata": json.dumps(ctx, separators=(",", ":")),
		"title": {"type": "plain_text", "text": "Extend allocation"},
		"submit": {"type": "plain_text", "text": "Extend allocation"},
		"close": {"type": "plain_text", "text": "Cancel"},
		"blocks": [
			_section(
				f"*{ctx['employee_name']} · {ctx['project_name']}*\n"
				f"Current end date: {_format_date(end)}\n"
				f"Hours per day: {ctx['hours']:g}",
			),
			{
				"type": "input",
				"block_id": ALLOCATION_DAYS_BLOCK_ID,
				"dispatch_action": True,
				"label": {
					"type": "plain_text",
					"text": "How many days would you like to continue?",
				},
				"hint": {
					"type": "plain_text",
					"text": (
						f"Calendar days from 1 to {ALLOCATION_EXTEND_MAX_DAYS}, "
						"starting after the current end date."
					),
				},
				# No min/max: Slack's own range error reads "Please complete
				# this required field", so the range is checked on submit.
				"element": {
					"type": "number_input",
					"action_id": ALLOCATION_DAYS_ACTION_ID,
					"is_decimal_allowed": False,
					"dispatch_action_config": {
						"trigger_actions_on": ["on_character_entered"],
					},
				},
			},
			_section(_extension_preview(ctx, days_raw)),
			_context(
				"Working days and holiday settings follow the current allocation."
			),
		],
	}


def build_changed_modal(ctx: dict, latest: dict | None) -> dict:
	"""Replace the duration modal when the allocation changed since the reminder."""
	return _notice_modal(
		format_allocation_changed(ctx, latest, "it can't be extended from here")
		if latest
		else "⚠️ This allocation no longer exists in ERP.",
	)


def build_superseded_modal() -> dict:
	"""Explain that a newer reminder replaced the one the modal was opened from."""
	return _notice_modal(SUPERSEDED_MESSAGE)


def _notice_modal(message: str) -> dict:
	"""Build a modal that only shows `message`, with nothing to submit."""
	return {
		"type": "modal",
		"title": {"type": "plain_text", "text": "Extend allocation"},
		"close": {"type": "plain_text", "text": "Close"},
		"blocks": [_section(message)],
	}
