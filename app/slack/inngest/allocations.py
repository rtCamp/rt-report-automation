"""Inngest functions for allocation-ending reminders and extensions."""

import asyncio
import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

import inngest

from app.core.adapters import inngest_client
from app.core.adapters.redis import redis_client
from app.core.utils import validate
from app.frappe.constants import (
	EMPLOYEE_ACTIVE_STATUS,
	EMPLOYEE_WEEKLY_SCHEDULE,
	PROJECT_SUPPRESSED_STATUSES,
	RESOURCE_ALLOCATION_DOCTYPE,
)
from app.frappe.service import FrappeService, FrappeValidationError
from app.slack.constants import (
	ALLOCATION_APPLIED_KEY,
	ALLOCATION_CONTINUATION_WINDOW_DAYS,
	ALLOCATION_DECISION_KEY,
	ALLOCATION_EXTEND_LOCK_KEY,
	ALLOCATION_EXTEND_LOCK_TTL,
	ALLOCATION_LIVE_REMINDER_KEY,
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
	format_reminder_superseded,
)

logger = logging.getLogger(__name__)


class AllocationBusyError(Exception):
	"""Another run holds the allocation's lock; raised so Inngest retries the step."""


class SlackUpdateError(Exception):
	"""Slack rejected a message update; raised so Inngest retries the step."""


def _date(value: object) -> dt.date:
	"""Parse an ERP date field."""
	return dt.date.fromisoformat(str(value))


def _next_working_day(day: dt.date) -> dt.date:
	"""Return the first weekday after `day`."""
	day += dt.timedelta(days=1)
	while day.weekday() >= 5:
		day += dt.timedelta(days=1)
	return day


def _working_hours(employee: dict, standard: float) -> float:
	"""Return the employee's daily working hours, defaulting to HR Settings'."""
	hours = float(employee.get("custom_working_hours") or 0)
	if employee.get("custom_work_schedule") == EMPLOYEE_WEEKLY_SCHEDULE:
		hours /= 5
	return hours or standard


def _picked_up_reason(
	allocation: dict,
	others: list[dict],
	working_hours: float,
) -> str | None:
	"""Why no extension is needed: the employee's time after it is already booked."""
	end = _date(allocation["allocation_end_date"])
	others = [
		o
		for o in others
		if o["employee"] == allocation["employee"] and o["name"] != allocation["name"]
	]
	if any(
		o["project"] == allocation["project"]
		and end
		< _date(o["allocation_start_date"])
		<= end + dt.timedelta(days=ALLOCATION_CONTINUATION_WINDOW_DAYS)
		for o in others
	):
		return "continues in a later allocation"

	day = _next_working_day(end)
	booked = sum(
		float(o.get("hours_allocated_per_day") or 0)
		for o in others
		if _date(o["allocation_start_date"]) <= day <= _date(o["allocation_end_date"])
	)
	if booked >= working_hours:
		return f"fully booked on {day} ({booked:g}h of {working_hours:g}h)"
	return None


def _skip_reason(
	allocation: dict,
	project: dict | None,
	employee: dict | None,
	manager: dict | None,
) -> str | None:
	"""Why no reporting manager can be reminded about the allocation, or None."""
	if not project:
		return "project not found"
	if project["status"] in PROJECT_SUPPRESSED_STATUSES:
		return f"project is {project['status']}"
	if not employee:
		return "employee not found"
	if employee["status"] != EMPLOYEE_ACTIVE_STATUS:
		return f"employee is {employee['status']}"
	relieving = employee.get("relieving_date")
	if relieving and _date(relieving) <= _date(allocation["allocation_end_date"]):
		return f"employee leaves on {relieving}"
	if not employee.get("reports_to"):
		return "employee has no reporting manager"
	if not manager or manager["status"] != EMPLOYEE_ACTIVE_STATUS:
		return f"reporting manager {employee['reports_to']} isn't active"
	if not manager.get("user_id"):
		return f"reporting manager {employee['reports_to']} has no ERP user"
	return None


async def _load_reminders() -> dict:
	"""Find allocations ending within the lead window and whom to remind.

	Returns:
		dict: `sent_on` (today, ISO) and `reminders`, each with the
			allocation `ctx`, the reporting manager's `email` and a `skip`
			reason (None when sendable).

	"""
	today = dt.datetime.now(ZoneInfo(ALLOCATION_TIMEZONE)).date()
	last_end = today + dt.timedelta(days=ALLOCATION_REMINDER_LEAD_DAYS)

	frappe_service = FrappeService()
	allocations = await frappe_service.get_allocations_ending_between(today, last_end)
	employee_ids = sorted({a["employee"] for a in allocations})
	employees = await frappe_service.get_employees(employee_ids)
	managers = await frappe_service.get_employees(
		sorted({e["reports_to"] for e in employees.values() if e.get("reports_to")}),
	)
	others = await frappe_service.get_allocations_overlapping(
		today + dt.timedelta(days=1),
		last_end + dt.timedelta(days=ALLOCATION_CONTINUATION_WINDOW_DAYS),
		employee_ids,
	)
	projects = await frappe_service.get_projects(
		sorted({a["project"] for a in allocations}),
	)
	standard_hours = await frappe_service.get_standard_working_hours()

	reminders = []
	for allocation in allocations:
		employee = employees.get(allocation["employee"])
		manager = managers.get(str((employee or {}).get("reports_to")))
		skip = _skip_reason(
			allocation,
			projects.get(allocation["project"]),
			employee,
			manager,
		) or _picked_up_reason(
			allocation,
			others,
			_working_hours(employee or {}, standard_hours),
		)
		reminders.append(
			{
				"ctx": allocation_context(allocation, today),
				"email": (manager or {}).get("user_id"),
				"skip": skip,
			},
		)
	return {"sent_on": today.isoformat(), "reminders": reminders}


def _supersede_live_reminder(ctx: dict, sent: dict) -> None:
	"""Track `sent` as the allocation's live reminder, closing the one it replaces."""
	previous = redis_client.set(
		ALLOCATION_LIVE_REMINDER_KEY.format(name=ctx["name"]),
		json.dumps(sent),
		ex=ALLOCATION_REMINDED_TTL,
		get=True,
	)
	if not previous:
		return

	live = json.loads(str(previous))
	text, blocks = format_reminder_superseded(ctx)
	# Cosmetic: the old reminder's buttons are already guarded by the
	# allocation's revision, so a failed update needs no retry.
	SlackNotifierService().update_message(live["channel"], live["ts"], text, blocks)


async def _send_reminder(email: str, ctx: dict) -> dict:
	"""DM one allocation's reminder to the reporting manager, at most once a day."""
	key = ALLOCATION_REMINDED_KEY.format(
		name=ctx["name"],
		end_date=ctx["end"],
		sent_on=ctx["sent_on"],
	)
	if not redis_client.set(key, "1", nx=True, ex=ALLOCATION_REMINDED_TTL):
		return {"status": "already_sent"}

	text, blocks = format_allocation_reminder(ctx)
	try:
		sent = await asyncio.to_thread(
			SlackNotifierService().send_dm,
			email,
			text,
			blocks,
		)
	except Exception:
		# Release the claim so Inngest's retry can deliver it.
		redis_client.delete(key)
		raise

	if not sent:
		redis_client.delete(key)
		return {"status": "delivery_failed"}

	await asyncio.to_thread(_supersede_live_reminder, ctx, sent)
	return {"status": "sent"}


async def preview_reminders() -> dict:
	"""List who today's run would remind, and why others are skipped, sending nothing.

	Returns:
		dict: `sent_on` (ISO date) and `recipients`, each with the
			`allocation`, `employee`, `project`, `end`, reporting `manager`
			and `skip` reason (None when it would be sent).

	"""
	loaded = await _load_reminders()
	return {
		"sent_on": loaded["sent_on"],
		"recipients": [
			{
				"allocation": r["ctx"]["name"],
				"employee": r["ctx"]["employee_name"],
				"project": r["ctx"]["project_name"],
				"end": r["ctx"]["end"],
				"manager": r["email"],
				"skip": r["skip"],
			}
			for r in loaded["reminders"]
		],
	}


@inngest_client.create_function(
	fn_id="send_allocation_reminders",
	trigger=[
		inngest.TriggerCron(cron=ALLOCATION_REMINDER_CRON),
		inngest.TriggerEvent(event="rt-report-automation/send_allocation_reminders"),
	],
	retries=1,
)
async def send_allocation_reminders(ctx: inngest.Context) -> dict:
	"""Remind reporting managers about allocations ending within the lead window.

	Runs every weekday, so an allocation is reminded about daily until it's
	extended past the window, removed, or its employee's time after the end
	date is fully booked elsewhere.

	Args:
		ctx (inngest.Context): The Inngest context.

	Returns:
		dict: `{"total": int, "sent": int, "skipped": int}` summary.

	"""
	loaded = await ctx.step.run("load", _load_reminders)
	sent_on = loaded["sent_on"]
	reminders = loaded["reminders"]

	for r in reminders:
		if r["skip"]:
			ctx.logger.info(f"Skipping {r['ctx']['name']}: {r['skip']}")

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
		f"Allocation reminders for {sent_on}: {sent} sent, "
		f"{len(reminders) - sent} skipped, {len(reminders)} total"
	)
	return {
		"total": len(reminders),
		"sent": sent,
		"skipped": len(reminders) - sent,
	}


async def _can_extend(frappe_service: FrappeService, email: str, employee: str) -> bool:
	"""Check `email` belongs to the employee's current, active reporting manager."""
	employees = await frappe_service.get_employees([employee])
	manager_id = (employees.get(employee) or {}).get("reports_to")
	if not manager_id:
		return False

	manager = (await frappe_service.get_employees([manager_id])).get(manager_id) or {}
	return (
		manager.get("status") == EMPLOYEE_ACTIVE_STATUS
		and (manager.get("user_id") or "").lower() == email.lower()
	)


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

		if not await _can_extend(frappe_service, email, allocation["employee"]):
			return {
				"status": "forbidden",
				"message": f"🔒 Only {ctx['employee_name']}'s reporting manager can "
				"extend this allocation. Nothing was changed.",
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
					"message": "⚠️ ERP couldn't extend the allocation, so nothing "
					f"was changed:\n> {exc}",
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


async def _close_live_reminder(
	name: str,
	message_ts: str,
	text: str,
	blocks: list,
) -> None:
	"""Show a decision on the allocation's live reminder too, and stop superseding it.

	A modal opened before a newer reminder went out is answered on the older
	message, which would otherwise leave the newer one's buttons live.
	"""
	key = ALLOCATION_LIVE_REMINDER_KEY.format(name=name)
	raw = redis_client.get(key)
	if not raw:
		return

	live = json.loads(str(raw))
	if live["ts"] != message_ts:
		await _show_outcome(live["channel"], live["ts"], text, blocks)
	redis_client.delete(key)


@inngest_client.create_function(
	fn_id="extend_allocation",
	trigger=inngest.TriggerEvent(event="rt-report-automation/extend_allocation"),
	retries=2,
)
async def extend_allocation(ctx: inngest.Context) -> dict:
	"""Extend an allocation from a submitted Slack duration modal.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- user_id (str): Slack user ID of the manager who submitted the modal.
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
			f"may not have been extended. Please try again.\n> {str(exc)[:300]}",
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
					sent_on=allocation.get("sent_on"),
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
	if outcome["status"] == "extended":
		try:
			await ctx.step.run(
				"close-live",
				_close_live_reminder,
				allocation["name"],
				message_ts,
				text,
				blocks,
			)
		except Exception as exc:
			ctx.logger.warning(
				f"Could not close live reminder for {allocation['name']}: {exc}",
			)
	return {"status": outcome["status"]}


@inngest_client.create_function(
	fn_id="decline_allocation",
	trigger=inngest.TriggerEvent(event="rt-report-automation/decline_allocation"),
	retries=2,
)
async def decline_allocation(ctx: inngest.Context) -> dict:
	"""Close a reminder whose reporting manager chose not to extend.

	The allocation is left untouched; the next weekday's reminder asks again.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- user_id (str): Slack user ID of the manager who clicked No.
			- allocation (dict): The allocation context from the reminder.
			- channel_id (str), message_ts (str): The reminder DM.

	Returns:
		dict: `{"status": "declined"}`.

	"""
	event_data = ctx.event.data
	validate(event_data, dict)

	allocation = event_data["allocation"]
	if not validate(allocation, dict):
		raise TypeError("Expected dict for 'allocation'")
	message_ts = str(event_data["message_ts"])

	text, blocks = format_reminder_outcome(
		allocation,
		"👍 Okay, the allocation stays unchanged for now. You'll be reminded "
		"again on the next weekday.",
	)
	await ctx.step.run(
		"notify",
		_show_outcome,
		str(event_data["channel_id"]),
		message_ts,
		text,
		blocks,
	)
	try:
		await ctx.step.run(
			"close-live",
			_close_live_reminder,
			allocation["name"],
			message_ts,
			text,
			blocks,
		)
	except Exception as exc:
		ctx.logger.warning(
			f"Could not close live reminder for {allocation['name']}: {exc}",
		)
	return {"status": "declined"}
