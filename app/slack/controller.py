"""Controller for the Slack /pms slash command and the PMS bulk audit trigger."""

import asyncio
import datetime as dt

import httpx
import inngest
from fastapi import APIRouter, Depends, Request, Response
from fastapi.logger import logger

from app.core.adapters import inngest_client
from app.core.adapters.redis import redis_client
from app.frappe.service import FrappeService
from app.slack.auth import safe_slack_response_url, verify_slack_signature
from app.slack.constants import (
	ALLOCATION_DAYS_ACTION_ID,
	ALLOCATION_DAYS_BLOCK_ID,
	ALLOCATION_DECISION_KEY,
	ALLOCATION_DECLINE_ACTION_ID,
	ALLOCATION_EXTEND_ACTION_ID,
	ALLOCATION_EXTEND_CALLBACK_ID,
	ALLOCATION_EXTEND_MAX_DAYS,
	ALLOCATION_REMINDED_TTL,
	AUDIT_PROJECT_SELECT_ACTION_ID,
	OPTIONS_TIME_BUDGET_SECONDS,
	PMS_SUBCOMMANDS,
	PMS_USAGE_TEXT,
)
from app.slack.inngest.allocations import preview_reminders
from app.slack.notifier import SlackNotifierService
from app.slack.utils.allocation_blocks import (
	build_changed_modal,
	build_extend_modal,
	parse_extension_days,
)
from app.slack.utils.helpers import (
	_format_audit_pending,
	_format_project_options,
	_format_project_picker,
	_lookup_picker_projects,
	_parse_interaction_payload,
)

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

allocation_router = APIRouter(
	prefix="/allocations",
	tags=["Allocation Reminders"],
)


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

	if subcommand not in PMS_SUBCOMMANDS:
		return {"response_type": "in_channel", "text": PMS_USAGE_TEXT}

	if subcommand == "audit" and not project_filter:
		# `in_channel`, not ephemeral: Slack fixes a message's visibility for
		# life, so an ephemeral picker would trap the finished report private.
		picker_text, picker_blocks = _format_project_picker()
		return {
			"response_type": "in_channel",
			"text": picker_text,
			"blocks": picker_blocks,
		}

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
		pending_text, pending_blocks = _format_audit_pending(
			str(project_filter),
			str(project_filter),
			rich=False,
		)
		return {
			"response_type": "in_channel",
			"text": pending_text,
			"blocks": pending_blocks,
		}

	return Response(status_code=200)


@router.post(
	"/interactions/options",
	summary="Slack select-menu options for the /pms audit project picker",
	description=(
		"Called by Slack as the user types in the project picker. Returns "
		"matching projects as select options."
	),
)
async def handle_select_options(request: Request):
	"""Return project options matching what the user has typed so far.

	Slack expects a synchronous `{"options": [...]}` reply within 3 seconds,
	so this queries Frappe inline rather than dispatching to Inngest.
	"""
	form = await request.form()
	payload = _parse_interaction_payload(form.get("payload"))

	if payload.get("action_id") != AUDIT_PROJECT_SELECT_ACTION_ID:
		return {"options": []}

	query = str(payload.get("value", "")).strip()
	user_id = str((payload.get("user") or {}).get("id", ""))

	try:
		projects = await asyncio.wait_for(
			_lookup_picker_projects(user_id, query),
			timeout=OPTIONS_TIME_BUDGET_SECONDS,
		)
	except TimeoutError:
		# Slack abandons this request at 3s, so return early rather than let
		# it drop the response and render nothing at all.
		logger.warning("Timed out building /pms audit picker options")
		return {"options": []}
	except Exception as e:
		# Empty list renders as "no results", better than Slack's error toast.
		logger.error(f"Error searching projects for /pms audit picker: {e}")
		return {"options": []}

	return {"options": _format_project_options(projects)}


@router.post(
	"/interactions",
	summary="Slack interactive component callbacks",
	description=(
		"Receives /pms audit picker selections and allocation reminder "
		"buttons and modals."
	),
)
async def handle_interaction(request: Request):
	"""Handle a project selection from the `/pms audit` picker.

	Mirrors `handle_slash_command`: acknowledge inside Slack's 3-second
	window with a visible "generating..." message, then let the Inngest
	function replace it in place via `response_url`.
	"""
	form = await request.form()
	payload = _parse_interaction_payload(form.get("payload"))

	if payload.get("type") == "view_submission":
		view = payload.get("view") or {}
		if view.get("callback_id") == ALLOCATION_EXTEND_CALLBACK_ID:
			return await _submit_extension(payload)
		return Response(status_code=200)

	actions = payload.get("actions") or []
	action = actions[0] if actions else {}

	allocation_handler = _ALLOCATION_ACTION_HANDLERS.get(str(action.get("action_id")))
	if allocation_handler:
		await allocation_handler(payload, action)
		return Response(status_code=200)

	if action.get("action_id") != AUDIT_PROJECT_SELECT_ACTION_ID:
		# Not ours -- ack so Slack shows no error.
		return Response(status_code=200)

	selected = action.get("selected_option") or {}
	project_id = selected.get("value")
	response_url = str(payload.get("response_url", ""))
	user_id = str((payload.get("user") or {}).get("id", ""))
	channel_id = str((payload.get("channel") or {}).get("id", ""))

	if not project_id:
		return Response(status_code=200)

	# Slack echoes the option label back, so naming the project costs no
	# extra lookup inside the 3-second window.
	project_label = str((selected.get("text") or {}).get("text") or project_id)

	# Posting directly gets the native task_card indicator that response_url
	# can't render. Skip DMs: the bot isn't a member of a two-person
	# conversation, so it would only burn a failing call on the 3-second path.
	pending_ts = None
	if channel_id and not channel_id.startswith("D"):
		card_text, card_blocks = _format_audit_pending(project_label, project_id)
		pending_ts = SlackNotifierService().post_to_channel(
			channel_id,
			card_text,
			card_blocks,
		)

	try:
		await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/pms_command",
				data={
					"user_id": user_id,
					"subcommand": "audit",
					"project_filter": project_id,
					"response_url": response_url,
					# Report goes here as its own message; the card is cleared.
					"channel_id": channel_id,
					"pending_ts": pending_ts,
				},
			),
		)
	except Exception as e:
		logger.error(f"Error sending pms_command event to Inngest: {e}")
		if pending_ts:
			SlackNotifierService().delete_message(channel_id, pending_ts)
		return {
			"response_type": "ephemeral",
			"replace_original": True,
			"text": (
				f"⚠️ Couldn't start the audit for `{project_id}`. "
				"Please try again in a moment."
			),
		}

	if pending_ts:
		# Card is already in the channel -- drop the now-redundant picker.
		return {"delete_original": True}

	# No channel post (DM, or bot not invited) -- show progress in the
	# picker's own message. `rich=False`: response_url silently discards a
	# message it can't render, task_card included.
	pending_text, pending_blocks = _format_audit_pending(
		project_label,
		project_id,
		rich=False,
	)
	pending_payload = {
		"response_type": "in_channel",
		"replace_original": True,
		"text": pending_text,
		"blocks": pending_blocks,
	}

	# POST rather than return it: Slack applies `replace_original` reliably to
	# an explicit response_url call, whereas a select menu's own HTTP reply
	# can be dropped, leaving the picker looking inert.
	safe_url = safe_slack_response_url(response_url)
	if not safe_url:
		logger.error("Refusing to POST to non-Slack response_url")
		return Response(status_code=200)

	async with httpx.AsyncClient(follow_redirects=False) as client:
		await client.post(safe_url, json=pending_payload)

	return Response(status_code=200)


def _reminder_message(payload: dict) -> tuple[str, str]:
	"""Return the (channel_id, ts) of the message a button was clicked on."""
	container = payload.get("container") or {}
	return str(container.get("channel_id", "")), str(container.get("message_ts", ""))


def _claim_decision(ctx: dict, decision: str) -> str | None:
	"""Record this reminder's decision, returning its key, or None if already made."""
	key = ALLOCATION_DECISION_KEY.format(
		name=ctx.get("name"),
		end_date=ctx.get("end"),
		sent_on=ctx.get("sent_on"),
	)
	if redis_client.set(key, decision, nx=True, ex=ALLOCATION_REMINDED_TTL):
		return key
	return None


async def _decline_extension(payload: dict, action: dict) -> None:
	"""Queue closing the reminder without touching the allocation."""
	ctx = _parse_interaction_payload(action.get("value"))
	channel_id, message_ts = _reminder_message(payload)
	user_id = str((payload.get("user") or {}).get("id", ""))

	decision_key = _claim_decision(ctx, f"decline:{user_id}")
	if not decision_key:
		# Already extended or declined; that run updates the message.
		return

	try:
		await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/decline_allocation",
				data={
					"user_id": user_id,
					"allocation": ctx,
					"channel_id": channel_id,
					"message_ts": message_ts,
				},
			),
		)
	except Exception as e:
		# The buttons stay, so the manager can click No again.
		logger.error(f"Error sending decline_allocation event to Inngest: {e}")
		redis_client.delete(decision_key)


# Holds the modal re-checks so they aren't garbage-collected mid-flight.
_modal_checks: set[asyncio.Task] = set()


async def _check_extend_modal(ctx: dict, view_id: str) -> None:
	"""Swap the open modal for a notice if the allocation changed since the reminder."""
	try:
		latest = await FrappeService().get_allocation(ctx["name"])
	except Exception as e:
		# Submitting re-checks the allocation anyway.
		logger.warning(f"Could not re-read {ctx['name']} for the modal: {e}")
		return

	if latest and str(latest["modified"]) == ctx.get("modified"):
		return
	await asyncio.to_thread(
		SlackNotifierService().update_view,
		view_id,
		"",
		build_changed_modal(ctx, latest),
	)


async def _open_extend_modal(payload: dict, action: dict) -> None:
	"""Open the duration modal, then re-check the allocation behind it."""
	ctx = _parse_interaction_payload(action.get("value"))
	channel_id, message_ts = _reminder_message(payload)
	ctx |= {"channel_id": channel_id, "message_ts": message_ts}
	view = await asyncio.to_thread(
		SlackNotifierService().open_view,
		str(payload.get("trigger_id", "")),
		build_extend_modal(ctx),
	)
	if not view:
		return

	# Opened first because the trigger_id expires in 3 seconds; ERP is read
	# after acknowledging the click.
	task = asyncio.create_task(_check_extend_modal(ctx, str(view["id"])))
	_modal_checks.add(task)
	task.add_done_callback(_modal_checks.discard)


async def _refresh_extend_preview(payload: dict, action: dict) -> None:
	"""Re-render the modal's preview for the days typed so far."""
	view = payload.get("view") or {}
	ctx = _parse_interaction_payload(view.get("private_metadata"))
	await asyncio.to_thread(
		SlackNotifierService().update_view,
		str(view.get("id", "")),
		str(view.get("hash", "")),
		build_extend_modal(ctx, action.get("value")),
	)


_ALLOCATION_ACTION_HANDLERS = {
	ALLOCATION_EXTEND_ACTION_ID: _open_extend_modal,
	ALLOCATION_DECLINE_ACTION_ID: _decline_extension,
	ALLOCATION_DAYS_ACTION_ID: _refresh_extend_preview,
}


def _days_error(message: str) -> dict:
	"""Show `message` under the modal's days input."""
	return {"response_action": "errors", "errors": {ALLOCATION_DAYS_BLOCK_ID: message}}


async def _submit_extension(payload: dict) -> dict:
	"""Validate the duration modal and queue the extension."""
	view = payload.get("view") or {}
	ctx = _parse_interaction_payload(view.get("private_metadata"))
	channel_id = str(ctx.pop("channel_id", ""))
	message_ts = str(ctx.pop("message_ts", ""))
	user_id = str((payload.get("user") or {}).get("id", ""))

	state = (view.get("state") or {}).get("values") or {}
	raw_days = (state.get(ALLOCATION_DAYS_BLOCK_ID) or {}).get(
		ALLOCATION_DAYS_ACTION_ID,
		{},
	)
	days = parse_extension_days(raw_days.get("value"))
	if days is None:
		return _days_error(
			f"Enter a whole number of days from 1 to {ALLOCATION_EXTEND_MAX_DAYS}.",
		)

	decision_key = _claim_decision(ctx, f"extend:{user_id}")
	if not decision_key:
		return _days_error("This reminder has already been answered.")

	# Slack allows 3 seconds to answer, so the reminder is updated by the
	# Inngest function rather than here.
	try:
		await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/extend_allocation",
				data={
					"user_id": user_id,
					"allocation": ctx,
					"days": days,
					"channel_id": channel_id,
					"message_ts": message_ts,
				},
			),
		)
	except Exception as e:
		logger.error(f"Error sending extend_allocation event to Inngest: {e}")
		redis_client.delete(decision_key)
		return _days_error("Couldn't start the extension. Please try again.")

	return {"response_action": "clear"}


@allocation_router.post(
	"/remind",
	summary="Send allocation-ending reminders now",
	description=(
		"Queues the same run as the weekday cron: reminds reporting managers "
		"about allocations ending within 14 days. Pass `dry_run=true` to get "
		"the recipients and skip reasons back without sending anything."
	),
)
async def trigger_allocation_reminders(*, dry_run: bool = False):
	"""Queue a run of `send_allocation_reminders`, or return a dry run's recipients."""
	if dry_run:
		try:
			return await preview_reminders()
		except Exception as e:
			logger.error(f"Error previewing allocation reminders: {e}")
			return Response(status_code=502)

	try:
		await inngest_client.send(
			inngest.Event(name="rt-report-automation/send_allocation_reminders"),
		)
	except Exception as e:
		logger.error(f"Error sending send_allocation_reminders event to Inngest: {e}")
		return Response(status_code=502)

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
	today = dt.datetime.now(dt.UTC).date()
	# "project:"/"unscoped" prefixes keep a scoped run's dedup id structurally
	# distinct from the daily unscoped run's -- a project literally named
	# "all" would otherwise collide with a bare sentinel and dedupe against it
	# for 24h.
	scope = f"project:{project_id}" if project_id is not None else "unscoped"
	try:
		await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/run_all_project_audits",
				# Deterministic per (day, scope): Inngest dedupes events sharing
				# an id within its 24h window, so a same-day retry/overlap of
				# the *same* scope is a no-op instead of a second full fan-out.
				id=f"run-all-{today}-{scope}-dry:{dry_run}",
				data={"project_id": project_id, "dry_run": dry_run},
			),
		)
	except Exception as e:
		logger.error(f"Error sending run_all_project_audits event to Inngest: {e}")
		return Response(status_code=502)

	return Response(status_code=200)
