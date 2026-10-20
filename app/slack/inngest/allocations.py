"""Inngest functions for allocation-ending reminders and extensions."""

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import inngest

from app.core.adapters import inngest_client
from app.core.adapters.redis import redis_client
from app.core.utils import validate
from app.frappe.constants import RESOURCE_ALLOCATION_DOCTYPE, RESOURCE_MANAGER_ROLES
from app.frappe.service import FrappeService, FrappeValidationError
from app.slack.constants import (
	ALLOCATION_CONTINUATION_WINDOW_DAYS,
	ALLOCATION_EXTEND_LOCK_KEY,
	ALLOCATION_EXTEND_LOCK_TTL,
	ALLOCATION_REMINDED_KEY,
	ALLOCATION_REMINDED_TTL,
	ALLOCATION_REMINDER_CRON,
	ALLOCATION_REMINDER_LEAD_DAYS,
	ALLOCATION_SUBMITTED_KEY,
	ALLOCATION_TIMEZONE,
)
from app.slack.notifier import SlackNotifierService
from app.slack.utils.allocation_blocks import (
	allocation_context,
	extension_dates,
	format_allocation_changed,
	format_allocation_reminder,
	format_extension_success,
	format_reminder_outcome,
)

logger = logging.getLogger(__name__)


def _is_continued(allocation: dict, upcoming: list[dict]) -> bool:
	"""Whether another allocation picks up the same employee and project right after."""
	return any(
		other["employee"] == allocation["employee"]
		and other["project"] == allocation["project"]
		and other["name"] != allocation["name"]
		for other in upcoming
	)


async def _send_reminder(email: str, ctx: dict) -> dict:
	"""DM one allocation's reminder to its PM, at most once per end date."""
	key = ALLOCATION_REMINDED_KEY.format(name=ctx["name"], end_date=ctx["end"])
	if not redis_client.set(key, "1", nx=True, ex=ALLOCATION_REMINDED_TTL):
		return {"status": "already_sent"}

	text, blocks = format_allocation_reminder(ctx)
	if SlackNotifierService().send_message(email, text, blocks):
		return {"status": "sent"}

	redis_client.delete(key)
	return {"status": "delivery_failed"}


@inngest_client.create_function(
	fn_id="send_allocation_reminders",
	trigger=[
		inngest.TriggerCron(cron=ALLOCATION_REMINDER_CRON),
		inngest.TriggerEvent(event="rt-report-automation/send_allocation_reminders"),
	],
	retries=1,
)
async def send_allocation_reminders(ctx: inngest.Context) -> dict:
	"""Remind PMs about allocations ending in `ALLOCATION_REMINDER_LEAD_DAYS` days.

	Args:
		ctx (inngest.Context): The Inngest context. A manual run's event.data
			may carry `dry_run` (bool) to list what would be sent without
			sending anything.

	Returns:
		dict: `{"total": int, "sent": int, "skipped": int}` summary.

	"""
	event_data = ctx.event.data or {}
	validate(event_data, dict)
	dry_run = bool(event_data.get("dry_run"))

	today = dt.datetime.now(ZoneInfo(ALLOCATION_TIMEZONE)).date()
	ends_on = today + dt.timedelta(days=ALLOCATION_REMINDER_LEAD_DAYS)

	frappe_service = FrappeService()
	allocations = await frappe_service.get_allocations_ending_on(ends_on)
	upcoming = await frappe_service.get_allocations_starting_between(
		ends_on + dt.timedelta(days=1),
		ends_on + dt.timedelta(days=ALLOCATION_CONTINUATION_WINDOW_DAYS),
	)
	allocations = [a for a in allocations if not _is_continued(a, upcoming)]

	managers = await frappe_service.get_project_managers(
		sorted({a["project"] for a in allocations}),
	)

	if dry_run:
		recipients = [
			{
				"allocation": a["name"],
				"employee": a.get("employee_name") or a["employee"],
				"project": a.get("project_name") or a["project"],
				"pm": managers.get(a["project"]),
			}
			for a in allocations
		]
		for r in recipients:
			ctx.logger.info(
				f"Dry run ({ends_on}): {r['allocation']} {r['employee']} on "
				f"{r['project']} -> {r['pm'] or 'no PM, would skip'}"
			)
		return {
			"total": len(allocations),
			"sent": 0,
			"skipped": 0,
			"dry_run": True,
			"recipients": recipients,
		}

	sent = 0
	for allocation in allocations:
		email = managers.get(allocation["project"])
		if not email:
			ctx.logger.warning(
				f"Skipping {allocation['name']}: project {allocation['project']} "
				"has no project manager"
			)
			continue

		result = await ctx.step.run(
			f"remind-{allocation['name']}",
			_send_reminder,
			email,
			allocation_context(allocation),
		)
		if result["status"] == "sent":
			sent += 1

	ctx.logger.info(
		f"Allocation reminders for {ends_on}: {sent} sent, "
		f"{len(allocations) - sent} skipped, {len(allocations)} total"
	)
	return {
		"total": len(allocations),
		"sent": sent,
		"skipped": len(allocations) - sent,
	}


async def _can_extend(frappe_service: FrappeService, email: str, project: str) -> bool:
	"""Check `email` is the project's PM and holds an allocation write role."""
	managers = await frappe_service.get_project_managers([project])
	if (managers.get(project) or "").lower() != email.lower():
		return False

	roles = await frappe_service.get_user_roles(email)
	return bool(RESOURCE_MANAGER_ROLES.intersection(roles))


async def _apply_extension(user_id: str, ctx: dict, days: int) -> dict:
	"""Re-check the allocation, extend it in ERP, and verify the saved change.

	Returns:
		dict: `{"status": ..., "message": str}` plus, when extended,
			`email`, `new_end` and `hours`. Status is one of "extended",
			"changed", "forbidden", "missing", "busy", "rejected" or
			"unverified".

	"""
	old_end = dt.date.fromisoformat(ctx["end"])
	_, new_end = extension_dates(old_end, days)

	lock_key = ALLOCATION_EXTEND_LOCK_KEY.format(name=ctx["name"])
	if not redis_client.set(lock_key, user_id, nx=True, ex=ALLOCATION_EXTEND_LOCK_TTL):
		return {
			"status": "busy",
			"message": "⏳ This allocation is already being extended. "
			"Check back in a minute.",
		}

	try:
		email = SlackNotifierService().get_user_email(user_id)
		if not email:
			return {
				"status": "forbidden",
				"message": "⚠️ Couldn't read your email from your Slack profile, "
				"so there's no way to match you to ERP. Nothing was changed.",
			}

		frappe_service = FrappeService()
		allocation = await frappe_service.get_allocation(ctx["name"])
		if not allocation:
			return {
				"status": "missing",
				"message": "⚠️ This allocation no longer exists in ERP. "
				"Nothing was changed.",
			}

		if not await _can_extend(frappe_service, email, allocation["project"]):
			return {
				"status": "forbidden",
				"message": "🔒 Only this project's manager, with allocation "
				"access in ERP, can extend this allocation. Nothing was changed.",
			}

		current_end = dt.date.fromisoformat(str(allocation["allocation_end_date"]))
		if current_end != new_end:
			if current_end != old_end:
				return {
					"status": "changed",
					"message": format_allocation_changed(ctx, allocation),
				}

			try:
				await frappe_service.extend_allocation(allocation, new_end)
			except FrappeValidationError as exc:
				return {
					"status": "rejected",
					"message": f"⚠️ ERP didn't extend the allocation: {exc}",
				}

			saved = await frappe_service.get_allocation(ctx["name"])
			if not saved or str(saved["allocation_end_date"]) != new_end.isoformat():
				return {
					"status": "unverified",
					"message": "⏳ The extension was sent to ERP but couldn't be "
					"confirmed yet. Check the allocation in ERP before trying again.",
				}
			allocation = saved

		return {
			"status": "extended",
			"message": "",
			"email": email,
			"new_end": new_end.isoformat(),
			"hours": float(allocation.get("hours_allocated_per_day") or 0),
		}
	finally:
		redis_client.delete(lock_key)


async def _record_extension(ctx: dict, email: str, days: int, new_end: str) -> None:
	"""Comment on the allocation who extended it, with old and new end dates."""
	await FrappeService().add_comment(
		RESOURCE_ALLOCATION_DOCTYPE,
		ctx["name"],
		(
			f"Extended from Slack by {email}: end date {ctx['end']} → {new_end} "
			f"({days} calendar days)."
		),
	)


async def _show_outcome(
	channel_id: str, message_ts: str, text: str, blocks: list
) -> bool:
	"""Replace the reminder DM with the extension's outcome."""
	return SlackNotifierService().update_message(channel_id, message_ts, text, blocks)


@inngest_client.create_function(
	fn_id="extend_allocation",
	trigger=inngest.TriggerEvent(event="rt-report-automation/extend_allocation"),
	retries=2,
)
async def extend_allocation(ctx: inngest.Context) -> dict:
	"""Extend an allocation from a submitted Slack duration modal.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- user_id (str): Slack user ID of the PM who submitted the modal.
			- allocation (dict): The allocation context from the reminder.
			- days (int): Calendar days to extend by.
			- channel_id (str), message_ts (str): The reminder DM, replaced
				with the outcome.

	Returns:
		dict: The outcome's `status`.

	"""
	event_data = ctx.event.data
	validate(event_data, dict)

	user_id = str(event_data["user_id"])
	allocation = event_data["allocation"]
	if not validate(allocation, dict):
		raise TypeError("Expected dict for 'allocation'")
	days = int(str(event_data["days"]))
	channel_id = str(event_data["channel_id"])
	message_ts = str(event_data["message_ts"])

	try:
		outcome = await ctx.step.run(
			"extend",
			_apply_extension,
			user_id,
			allocation,
			days,
		)
	except Exception as exc:
		ctx.logger.error(f"Extending {allocation['name']} failed: {exc}")
		outcome = {
			"status": "rejected",
			"message": "⚠️ Something went wrong reaching ERP, so the allocation "
			"may not have been extended. Please try again.",
		}

	if outcome["status"] == "extended":
		try:
			await ctx.step.run(
				"record",
				_record_extension,
				allocation,
				outcome["email"],
				days,
				outcome["new_end"],
			)
		except Exception as exc:
			ctx.logger.error(
				f"Could not record extension of {allocation['name']}: {exc}",
			)

		text, blocks = format_extension_success(
			allocation,
			dt.date.fromisoformat(str(outcome["new_end"])),
			float(str(outcome["hours"])),
			days,
		)
	else:
		retry = outcome["status"] == "rejected"
		if retry:
			redis_client.delete(
				ALLOCATION_SUBMITTED_KEY.format(
					name=allocation["name"],
					end_date=allocation["end"],
				),
			)
		text, blocks = format_reminder_outcome(
			allocation,
			outcome["message"],
			retry=retry,
		)

	await ctx.step.run(
		"notify",
		_show_outcome,
		channel_id,
		message_ts,
		text,
		blocks,
	)
	return {"status": outcome["status"]}
