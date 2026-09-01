"""Inngest functions for Slack integration."""

import datetime
import logging

import httpx
import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.utils import to_unix_inclusive_date_range, validate
from app.frappe.constants import PROJECT_MANAGER_FIELD
from app.frappe.service import FrappeService
from app.llm.models.summarization import ProjectMetadata, SlackMetadata
from app.slack.constants import SLACK_API_RATE_LIMIT
from app.slack.notifier import SlackNotifierService
from app.slack.service import SlackService
from app.slack.utils.helpers import (
	_build_audit_report,
	_filter_projects,
	_format_missing_fields,
	_format_multiple_matches,
	_format_projects_list,
	_resolve_delivery_manager_override,
	_send_project_audit,
)

logger = logging.getLogger(__name__)


@inngest_client.create_function(
	fn_id="fetch_slack",
	trigger=inngest.TriggerEvent(event="rt-report-automation/fetch_slack"),
	retries=2,
	throttle=inngest.Throttle(
		limit=SLACK_API_RATE_LIMIT,
		period=datetime.timedelta(minutes=1),
	),
)
async def fetch_slack(ctx: inngest.Context):
	"""Inngest function to fetch standup messages from Slack.

	Retrieves standup messages from a specified Slack channel within a given
	date range and returns formatted text with standup data grouped by date.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- slack_metadata (dict): Slack configuration with channel_slug
			- project_metadata (dict): Project details with start_date and end_date

	Returns:
		str: Formatted text with standup messages grouped by date headers.
			Each section contains the standup text from Slack threads.

	Raises:
		TypeError: If event data or metadata types don't match expected types.
		ValueError: If validation fails for metadata or required fields are missing.
		Exception: For any other errors during Slack data fetching.

	"""
	try:
		event_data = ctx.event.data
		validate(event_data, dict)

		# Extract slack_metadata and project_metadata.
		slack_data = event_data.get("slack_metadata")
		project_data = event_data.get("project_metadata")

		slack_metadata = SlackMetadata.model_validate(slack_data)
		project_metadata = ProjectMetadata.model_validate(project_data)

		start_ts, end_ts = to_unix_inclusive_date_range(
			project_metadata.start_date,
			project_metadata.end_date,
		)

		slack_service = SlackService()

		return slack_service.get_standups(
			slack_metadata.channel_slug,
			start_ts,
			end_ts,
		)
	except ValidationError as e:
		ctx.logger.error(f"Validation error for SlackMetadata/ProjectMetadata: {e}")
		raise ValueError(f"Validation error: {e}")
	except KeyError as e:
		ctx.logger.error(f"Missing required field in event data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error in fetch_slack: {e}")
		raise


@inngest_client.create_function(
	fn_id="handle_pms_command",
	trigger=inngest.TriggerEvent(event="rt-report-automation/pms_command"),
	retries=2,
)
async def handle_pms_command(ctx: inngest.Context):
	"""Inngest function to handle the Slack /pms slash command.

	Resolves the requesting Slack user's email, looks up their Frappe PMS
	projects by matching that email against the project manager field, and
	replies via the slash command's `response_url` with the project list, a
	missing-fields report, or a full per-project audit.

	For "audit" specifically: if `project_filter` doesn't match any of the
	requester's own PM'd projects, and they hold the Delivery Manager Frappe
	role, they can still audit that project by its exact ID (see
	`_resolve_delivery_manager_override`) -- lets a Delivery Manager check
	in on any project without being its PM.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- user_id (str): Slack user ID of the command's caller.
			- subcommand (str): "projects", "missing-fields", or "audit".
			- project_filter (str | None): Project name/ID to narrow the
				results down to a single project. Optional for "projects"
				and "missing-fields"; required for "audit".
			- response_url (str): Slack's delayed-response webhook URL.

	"""
	event_data = ctx.event.data
	validate(event_data, dict)

	user_id = str(event_data["user_id"])
	subcommand = str(event_data["subcommand"])
	project_filter = event_data.get("project_filter")
	response_url = str(event_data["response_url"])

	notifier = SlackNotifierService()
	email = notifier.get_user_email(user_id)

	blocks: list[dict] | None = None

	if not email:
		text = "Couldn't resolve your email from your Slack profile."
	else:
		try:
			frappe_service = FrappeService()
			projects = await frappe_service.get_projects_by_manager_email(email)

			if project_filter:
				projects = _filter_projects(projects, str(project_filter))

			if not projects and project_filter and subcommand == "audit":
				override_project = await _resolve_delivery_manager_override(
					frappe_service, email, str(project_filter)
				)
				if override_project:
					projects = [override_project]

			if project_filter and not projects:
				text = (
					f"🤷 No project matching '{project_filter}' found among "
					"your projects."
				)
			elif subcommand == "projects":
				text, blocks = _format_projects_list(projects, user_id)
			elif subcommand == "audit":
				if len(projects) > 1:
					text = _format_multiple_matches(projects, str(project_filter))
				else:
					text, blocks = await _build_audit_report(
						ctx, frappe_service, projects[0]
					)
			else:
				text = _format_missing_fields(projects)
		except Exception as exc:
			# Frappe/GitHub calls now raise on a failed fetch rather than
			# silently degrading to an empty/misleading result -- caught here
			# so the requester still gets a reply instead of being stuck on
			# the "Generating..." message until Inngest's retries run out.
			ctx.logger.error(f"Error building /pms response for {user_id}: {exc}")
			text = "⚠️ Something went wrong reaching Next PMS. Please try again shortly."

	payload: dict[str, object] = {
		"response_type": "in_channel",
		"text": text,
		"replace_original": True,
	}
	if blocks:
		payload["blocks"] = blocks

	async with httpx.AsyncClient() as client:
		response = await client.post(response_url, json=payload)

	if response.status_code >= 400:
		# httpx doesn't raise for non-2xx by default -- an expired response_url
		# or a rejected Block Kit payload would otherwise mark this job
		# successful while the user is left on the "Generating..." message.
		ctx.logger.error(
			"Failed to deliver /pms response to Slack: %s %s",
			response.status_code,
			response.text,
		)
		response.raise_for_status()


@inngest_client.create_function(
	fn_id="audit_and_send_project",
	trigger=inngest.TriggerEvent(event="rt-report-automation/audit_project"),
	retries=1,
	# Caps how many of these run at once across a fan-out of many projects,
	# so a big batch doesn't hammer the GitHub/LLM APIs simultaneously.
	concurrency=[inngest.Concurrency(limit=5)],
)
async def audit_and_send_project(ctx: inngest.Context) -> dict:
	"""Inngest function to build and DM one project's audit.

	Triggered per-project by `run_all_project_audits`'s fan-out -- each
	project is its own independent Inngest job with its own retry, so one
	project failing (e.g. a transient GitHub API error) doesn't block or
	crash the rest of the batch, unlike a single sequential loop.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- project (dict): One project record, as returned by
				`FrappeService.get_billable_open_projects`.

	Returns:
		dict: `{"status": "sent" | "skipped", ...}`.

	"""
	event_data = ctx.event.data
	validate(event_data, dict)
	project = event_data["project"]

	if not validate(project, dict):
		raise TypeError("Expected dict for 'project'")

	project_id = project["name"]
	email = project.get(PROJECT_MANAGER_FIELD)

	if not email:
		ctx.logger.warning(f"Skipping {project_id}: no project manager set")
		return {"status": "skipped", "reason": "no_manager"}

	frappe_service = FrappeService()
	text, blocks = await _build_audit_report(ctx, frappe_service, project)

	result = await ctx.step.run("send", _send_project_audit, email, text, blocks)
	if not result["delivered"]:
		ctx.logger.warning(f"Skipping {project_id}: Slack delivery failed for {email}")
		return {"status": "skipped", "reason": "delivery_failed"}

	return {"status": "sent"}


@inngest_client.create_function(
	fn_id="run_all_project_audits",
	trigger=inngest.TriggerEvent(event="rt-report-automation/run_all_project_audits"),
	retries=1,
)
async def run_all_project_audits(ctx: inngest.Context) -> dict:
	"""Inngest function to fan out an audit-and-DM job for every open, billable project.

	Triggered by Frappe's scheduler pinging `POST /audit/run-all` -- its
	only job is to send this ping; all the real work happens in the
	per-project fan-out. Uses `ctx.group.parallel` + `ctx.step.invoke`
	(the same pattern already used by `summarization_workflow` in
	app/llm/inngest/main.py) so each project's audit runs as its own
	independently-retried Inngest function invocation rather than one
	sequential loop where a single project's failure could take down the
	whole batch.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- project_id (str | None): If set, scope the run to just this
				project instead of every billable open project -- lets the
				trigger endpoint be exercised safely against a single project.
			- dry_run (bool): If true, resolve and log which project(s) would
				be audited but skip invoking any audit-and-DM job -- lets the
				trigger endpoint be validated with zero side effects.

	Returns:
		dict: `{"total": int, "sent": int, "skipped": int}` summary. When
			`dry_run` is set, `sent`/`skipped` are always 0 and a `dry_run: True`
			key is included.

	"""
	event_data = ctx.event.data or {}
	validate(event_data, dict)
	project_id = event_data.get("project_id")
	dry_run = bool(event_data.get("dry_run"))

	async def _invoke_project_audit(project: dict) -> dict:
		"""Invoke one project's audit job, isolating its failure from the rest.

		Catches only `Exception`, never `BaseException` -- confirmed by
		inspecting the installed SDK that Inngest's own internal
		step-orchestration signals (`ResponseInterrupt`/`SkipInterrupt`)
		subclass `BaseException` directly, so this can't accidentally
		swallow them. A genuine failure (e.g. `audit_and_send_project`
		exhausting its own retries) is recorded as skipped instead of
		propagating up through `ctx.group.parallel` and crashing this
		whole orchestrator -- which defeats the point of fanning out.
		"""
		try:
			return await ctx.step.invoke(
				f"audit-{project['name']}",
				function=audit_and_send_project,
				data={"project": project},
			)
		except Exception as exc:
			ctx.logger.error(f"Skipping {project['name']}: audit job failed: {exc}")
			return {"status": "skipped", "reason": "job_failed"}

	frappe_service = FrappeService()
	projects = await frappe_service.get_billable_open_projects()

	if project_id is not None:
		projects = [p for p in projects if p["name"] == project_id]

	if dry_run:
		ctx.logger.info(
			f"Dry run: would audit {len(projects)} project(s): "
			f"{[p['name'] for p in projects]}"
		)
		return {"total": len(projects), "sent": 0, "skipped": 0, "dry_run": True}

	steps = [
		(lambda project=project: _invoke_project_audit(project)) for project in projects
	]
	results = await ctx.group.parallel(tuple(steps))

	sent = sum(1 for r in results if r and r.get("status") == "sent")
	skipped = len(results) - sent

	ctx.logger.info(
		f"Bulk audit: {sent} sent, {skipped} skipped, {len(projects)} total"
	)
	return {"total": len(projects), "sent": sent, "skipped": skipped}
