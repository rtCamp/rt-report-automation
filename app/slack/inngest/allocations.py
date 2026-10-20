"""Inngest functions for allocation-ending reminders and extensions."""

import asyncio
import datetime as dt
import logging
from zoneinfo import ZoneInfo

import inngest

from app.core.adapters import inngest_client
from app.core.adapters.redis import redis_client
from app.core.utils import validate
from app.frappe.constants import (
	PROJECT_MANAGER_FIELD,
	PROJECT_SUPPRESSED_STATUSES,
	RESOURCE_ALLOCATION_DOCTYPE,
	RESOURCE_MANAGER_ROLES,
)
from app.frappe.service import FrappeService, FrappeValidationError
from app.slack.constants import (
	ALLOCATION_APPLIED_KEY,
	ALLOCATION_CONTINUATION_WINDOW_DAYS,
	ALLOCATION_DECISION_KEY,
	ALLOCATION_EXTEND_LOCK_KEY,
	ALLOCATION_EXTEND_LOCK_TTL,
	ALLOCATION_REMINDED_KEY,
	ALLOCATION_REMINDED_TTL,
	ALLOCATION_REMINDER_CRON,
	ALLOCATION_REMINDER_LEAD_DAYS,
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


class AllocationBusyError(Exception):
	"""Another run holds the allocation's lock; raised so Inngest retries the step."""


class SlackUpdateError(Exception):
	"""Slack rejected a message update; raised so Inngest retries the step."""


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
	try:
		sent = await asyncio.to_thread(
			SlackNotifierService().send_message,
			email,
			text,
			blocks,
		)
	except Exception:
		# Release the claim so Inngest's retry can deliver it.
		redis_client.delete(key)
		raise

	if sent:
		return {"status": "sent"}

	redis_client.delete(key)
	return {"status": "delivery_failed"}


def _skip_reason(project: dict | None, roles: dict[str, list[str]]) -> str | None:
	"""Why an allocation's PM shouldn't be reminded, or None if they should."""
	if not project:
		return "project not found"
	if project["status"] in PROJECT_SUPPRESSED_STATUSES:
		return f"project is {project['status']}"
	email = project.get(PROJECT_MANAGER_FIELD)
	if not email:
		return "project has no project manager"
	if not RESOURCE_MANAGER_ROLES.intersection(roles.get(email, [])):
		return f"{email} has no allocation role in ERP"
	return None


async def _load_reminders() -> dict:
	"""Find allocations ending in `ALLOCATION_REMINDER_LEAD_DAYS` days and their PMs.

	Returns:
		dict: `ends_on` (ISO date) and `reminders`, each with the allocation
			`ctx`, the PM `email` and a `skip` reason (None when sendable).

	"""
	today = dt.datetime.now(ZoneInfo(ALLOCATION_TIMEZONE)).date()
	ends_on = today + dt.timedelta(days=ALLOCATION_REMINDER_LEAD_DAYS)

	frappe_service = FrappeService()
	allocations = await frappe_service.get_allocations_ending_on(ends_on)
	upcoming = await frappe_service.get_allocations_starting_between(
		ends_on + dt.timedelta(days=1),
		ends_on + dt.timedelta(days=ALLOCATION_CONTINUATION_WINDOW_DAYS),
	)
	allocations = [a for a in allocations if not _is_continued(a, upcoming)]

	projects = await frappe_service.get_projects(
		sorted({a["project"] for a in allocations}),
	)
	emails = {
		p[PROJECT_MANAGER_FIELD]
		for p in projects.values()
		if p.get(PROJECT_MANAGER_FIELD)
	}
	roles = {email: await frappe_service.get_user_roles(email) for email in emails}

	reminders = []
	for allocation in allocations:
		project = projects.get(allocation["project"])
		reminders.append(
			{
				"ctx": allocation_context(allocation),
				"email": (project or {}).get(PROJECT_MANAGER_FIELD),
				"skip": _skip_reason(project, roles),
			},
		)
	return {"ends_on": ends_on.isoformat(), "reminders": reminders}


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

	Only a project's manager who holds an allocation role in ERP is reminded,
	since only they can act on the reminder.

	Args:
		ctx (inngest.Context): The Inngest context. A manual run's event.data
			may carry `dry_run` (bool) to list what would be sent without
			sending anything.

	Returns:
		dict: `{"total": int, "sent": int, "skipped": int}` summary, plus
			`recipients` on a dry run.

	"""
	event_data = ctx.event.data or {}
	validate(event_data, dict)
	dry_run = bool(event_data.get("dry_run"))

	loaded = await ctx.step.run("load", _load_reminders)
	ends_on = loaded["ends_on"]
	reminders = loaded["reminders"]

	for r in reminders:
		if r["skip"]:
			ctx.logger.warning(f"Skipping {r['ctx']['name']}: {r['skip']}")

	if dry_run:
		recipients = [
			{
				"allocation": r["ctx"]["name"],
				"employee": r["ctx"]["employee_name"],
				"project": r["ctx"]["project_name"],
				"pm": r["email"],
				"skip": r["skip"],
			}
			for r in reminders
		]
		for r in recipients:
			ctx.logger.info(
				f"Dry run ({ends_on}): {r['allocation']} {r['employee']} on "
				f"{r['project']} -> {r['pm']}"
				+ (f" (skip: {r['skip']})" if r["skip"] else ""),
			)
		return {
			"total": len(reminders),
			"sent": 0,
			"skipped": 0,
			"dry_run": True,
			"recipients": recipients,
		}

	sent = 0
	for r in reminders:
		if r["skip"]:
			continue

		try:
			result = await ctx.step.run(
				f"remind-{r['ctx']['name']}",
				_send_reminder,
				r["email"],
				r["ctx"],
			)
		except Exception as exc:
			ctx.logger.error(f"Could not remind about {r['ctx']['name']}: {exc}")
			continue
		if result["status"] == "sent":
			sent += 1

	ctx.logger.info(
		f"Allocation reminders for {ends_on}: {sent} sent, "
		f"{len(reminders) - sent} skipped, {len(reminders)} total"
	)
	return {
		"total": len(reminders),
		"sent": sent,
		"skipped": len(reminders) - sent,
	}


async def _can_extend(frappe_service: FrappeService, email: str, project: str) -> bool:
	"""Check `email` is the project's PM and holds an allocation write role."""
	managers = await frappe_service.get_project_managers([project])
	if (managers.get(project) or "").lower() != email.lower():
		return False

	roles = await frappe_service.get_user_roles(email)
	return bool(RESOURCE_MANAGER_ROLES.intersection(roles))


def _acquire_lock(name: str, run_id: str) -> None:
	"""Take the allocation's extension lock, re-entrant for retries of `run_id`.

	Raises:
		AllocationBusyError: If another run holds it.

	"""
	key = ALLOCATION_EXTEND_LOCK_KEY.format(name=name)
	if redis_client.set(key, run_id, nx=True, ex=ALLOCATION_EXTEND_LOCK_TTL):
		return
	if redis_client.get(key) != run_id:
		raise AllocationBusyError(f"{name} is being extended by another run")


async def _apply_extension(run_id: str, user_id: str, ctx: dict, days: int) -> dict:
	"""Re-check the allocation, extend it in ERP, and verify the saved change.

	The write only goes ahead if the allocation is still at the revision the
	reminder showed (`ctx["modified"]`), so any edit since -- end date, hours
	or otherwise -- is reported instead of overwritten. A retry of the same
	run recognises its own earlier write.

	Returns:
		dict: `{"status": ..., "message": str}` plus, when extended,
			`email`, `new_end` and `hours`. Status is one of "extended",
			"changed", "forbidden", "missing", "rejected" or "unverified".

	Raises:
		AllocationBusyError: If another run is extending it; Inngest retries.

	"""
	_, new_end = extension_dates(dt.date.fromisoformat(ctx["end"]), days)

	_acquire_lock(ctx["name"], run_id)
	try:
		email = await asyncio.to_thread(SlackNotifierService().get_user_email, user_id)
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

		applied_key = ALLOCATION_APPLIED_KEY.format(
			name=ctx["name"],
			revision=ctx.get("modified"),
		)
		replayed = (
			redis_client.get(applied_key) == run_id
			and str(allocation["allocation_end_date"]) == new_end.isoformat()
		)
		if not replayed:
			if str(allocation["modified"]) != ctx.get("modified"):
				return {
					"status": "changed",
					"message": format_allocation_changed(ctx, allocation),
				}

			# Marked before writing: a crash after the PUT still lets a retry
			# of this run claim the change as its own.
			redis_client.set(applied_key, run_id, ex=ALLOCATION_REMINDED_TTL)
			try:
				await frappe_service.extend_allocation(allocation, new_end)
			except FrappeValidationError as exc:
				redis_client.delete(applied_key)
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
		redis_client.delete(ALLOCATION_EXTEND_LOCK_KEY.format(name=ctx["name"]))


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
) -> None:
	"""Replace the reminder DM with the extension's outcome.

	Raises:
		SlackUpdateError: If Slack rejects the update, so Inngest retries.

	"""
	if not await asyncio.to_thread(
		SlackNotifierService().update_message,
		channel_id,
		message_ts,
		text,
		blocks,
	):
		raise SlackUpdateError(f"Could not update message {message_ts}")


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

	text, blocks = format_reminder_outcome(
		allocation,
		"⏳ Extending the allocation in ERP…",
	)
	try:
		await ctx.step.run(
			"pending",
			_show_outcome,
			channel_id,
			message_ts,
			text,
			blocks,
		)
	except Exception as exc:
		# Cosmetic only; the extension must still run.
		ctx.logger.warning(f"Could not show pending state: {exc}")

	try:
		outcome = await ctx.step.run(
			"extend",
			_apply_extension,
			ctx.run_id,
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
				ALLOCATION_DECISION_KEY.format(
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


async def _record_decline(user_id: str, ctx: dict) -> None:
	"""Comment on the allocation who declined to extend it from Slack."""
	email = await asyncio.to_thread(SlackNotifierService().get_user_email, user_id)
	await FrappeService().add_comment(
		RESOURCE_ALLOCATION_DOCTYPE,
		ctx["name"],
		(
			f"Extension declined from Slack by {email or f'Slack user {user_id}'}: "
			f"end date stays {ctx['end']}."
		),
	)


@inngest_client.create_function(
	fn_id="decline_allocation",
	trigger=inngest.TriggerEvent(event="rt-report-automation/decline_allocation"),
	retries=2,
)
async def decline_allocation(ctx: inngest.Context) -> dict:
	"""Close a reminder whose PM chose not to extend, and note it in ERP.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- user_id (str): Slack user ID of the PM who clicked No.
			- allocation (dict): The allocation context from the reminder.
			- channel_id (str), message_ts (str): The reminder DM.

	Returns:
		dict: `{"status": "declined"}`.

	"""
	event_data = ctx.event.data
	validate(event_data, dict)

	user_id = str(event_data["user_id"])
	allocation = event_data["allocation"]
	if not validate(allocation, dict):
		raise TypeError("Expected dict for 'allocation'")

	text, blocks = format_reminder_outcome(
		allocation,
		"👍 Okay, the allocation stays unchanged.",
	)
	try:
		await ctx.step.run(
			"notify",
			_show_outcome,
			str(event_data["channel_id"]),
			str(event_data["message_ts"]),
			text,
			blocks,
		)
	except Exception as exc:
		# Still record the decline in ERP.
		ctx.logger.error(f"Could not close reminder for {allocation['name']}: {exc}")
	await ctx.step.run("record", _record_decline, user_id, allocation)
	return {"status": "declined"}
