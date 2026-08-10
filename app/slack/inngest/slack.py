"""Inngest functions for Slack integration."""

import asyncio
import datetime
import logging
import re

import httpx
import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.config import settings
from app.core.utils import to_unix_inclusive_date_range, validate
from app.frappe.constants import (
	BOOLEAN_FIELDS,
	PROJECT_DETAIL_FIELDS,
	PROJECT_DETAIL_SECTIONS,
	PROJECT_MANAGER_FIELD,
	RISK_BLOCKED_STATUS,
	RISK_LEVEL_ORDER,
	RISK_MITIGATED_STATUS,
	TASK_CLOSED_STATUSES,
	TODO_STATUS_TO_TASK_STATUS,
)
from app.frappe.service import FrappeService
from app.github.services.github_data import GitHubDataService
from app.github.utils.constants import BLOCKED_ISSUE_STATUS_NAME
from app.llm.models.summarization import ProjectMetadata, SlackMetadata
from app.slack.constants import SLACK_API_RATE_LIMIT
from app.slack.notifier import SlackNotifierService
from app.slack.service import SlackService

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


_STATUS_ICONS = {
	"Open": "🟢",
	"Completed": "✅",
	"Cancelled": "🚫",
}


def _format_projects_list(
	projects: list[dict],
	user_id: str,
) -> tuple[str, list[dict] | None]:
	"""Build the /pms projects response as fallback text plus Block Kit blocks.

	Uses a real `table` block (clickable project name links, inline-code IDs),
	a `rich_text` block for the status legend with inline bold styles, an
	`actions` block with a primary "Open in Next PMS" button, and a `context`
	block for the audit tip.

	Returns:
		tuple[str, list[dict] | None]: A plain-text fallback (shown in
			notifications/surfaces that don't render blocks) and the Block
			Kit blocks list to render in Slack, or ``None`` blocks when
			there are no projects to show.

	"""
	if not projects:
		return (
			f"\U0001f937 No projects found where <@{user_id}> is the project manager.",
			None,
		)

	base_url = str(settings.FRAPPE_BASE_URL).rstrip("/")
	total = len(projects)

	# Header
	blocks: list[dict] = [_header_block(f"\U0001f4c1 Projects ({total})")]

	# Rich-text intro: @mention + status legend with inline bold
	legend_elements: list[dict] = [
		{"type": "text", "text": "Projects managed by "},
		{"type": "user", "user_id": user_id},
		{"type": "text", "text": f"  \u00b7  {total} total\n\n"},
	]
	for status, icon in _STATUS_ICONS.items():
		legend_elements.append({"type": "text", "text": f"{icon} "})
		legend_elements.append(
			{"type": "text", "text": status, "style": {"bold": True}}
		)
		legend_elements.append({"type": "text", "text": "   "})
	blocks.append(
		{
			"type": "rich_text",
			"elements": [{"type": "rich_text_section", "elements": legend_elements}],
		}
	)
	blocks.append({"type": "divider"})

	# Table: PROJECT (linked) | ID (inline code) | STATUS
	header_row = [
		_raw_text_cell("PROJECT"),
		_raw_text_cell("ID"),
		_raw_text_cell("STATUS"),
	]
	column_settings = [{"is_wrapped": True}, {}, {}]
	table_rows = []
	for p in projects:
		project_url = f"{base_url}/next-pms/projects/{p['name']}"
		status_icon = _STATUS_ICONS.get(p["status"], "\u26aa")
		# ID cell: inline-code style via rich_text
		id_cell = {
			"type": "rich_text",
			"elements": [
				{
					"type": "rich_text_section",
					"elements": [
						{"type": "text", "text": p["name"], "style": {"code": True}}
					],
				}
			],
		}
		table_rows.append(
			[
				_link_cell(p["project_name"], project_url),
				id_cell,
				_raw_text_cell(f"{status_icon} {p['status']}"),
			]
		)
	blocks.append(
		{
			"type": "table",
			"rows": [header_row, *table_rows],
			"column_settings": column_settings,
		}
	)
	blocks.append({"type": "divider"})

	# Actions: primary button -> Next PMS project list
	blocks.append(
		{
			"type": "actions",
			"elements": [
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "\U0001f310 Open Next PMS",
						"emoji": True,
					},
					"style": "primary",
					"url": f"{base_url}/next-pms/projects",
					"action_id": "open_next_pms_projects",
				}
			],
		}
	)

	# Context: audit tip
	blocks.append(
		{
			"type": "context",
			"elements": [
				{
					"type": "mrkdwn",
					"text": (
						"\U0001f4a1 Run `/pms audit <PROJECT-ID>` for the full "
						"health report on any project."
					),
				}
			],
		}
	)

	fallback_text = f"\U0001f4c1 Projects managed by <@{user_id}> ({total} total)"
	return fallback_text, blocks


def _format_field_value(project: dict, fieldname: str) -> str:
	"""Format a single field's value: Yes/No for booleans, — if empty."""
	value = project.get(fieldname)
	if fieldname in BOOLEAN_FIELDS:
		return "*Yes*" if value else "*No*"
	return f"*{value}*" if value else "—"


def _format_project_detail(project: dict) -> str:
	"""Format a full sectioned field report for a single project."""
	header = f"🗂️ *{project['project_name']}* · `{project['name']}`\n"
	sections = []
	for section_title, fields in PROJECT_DETAIL_SECTIONS:
		lines = [
			f"{icon} {label}: {_format_field_value(project, fieldname)}"
			for fieldname, label, icon in fields
		]
		sections.append(f"*{section_title}*\n" + "\n".join(lines))

	return header + "\n\n".join(sections)


def _format_missing_summary(projects: list[dict]) -> str:
	"""Format a compact missing-field call-out per project."""
	header = f"📋 *Missing Fields Report ({len(projects)} projects)*\n"
	lines = []
	for project in projects:
		missing = [
			label
			for fieldname, label in PROJECT_DETAIL_FIELDS
			if fieldname not in BOOLEAN_FIELDS and not project.get(fieldname)
		]
		title = f"*{project['project_name']}* · `{project['name']}`"
		if missing:
			lines.append(f"⚠️ {title}\n     Missing: {', '.join(missing)}")
		else:
			lines.append(f"✅ {title}\n     All fields complete")

	return header + "\n".join(lines)


def _format_missing_fields(projects: list[dict]) -> str:
	"""Format the missing-fields report.

	Shows a full sectioned detail view (matching the Next PMS project page)
	when narrowed to a single project, otherwise a compact per-project
	missing-field summary.
	"""
	if not projects:
		return "🤷 No projects found where you're the project manager."

	if len(projects) == 1:
		return _format_project_detail(projects[0])

	return _format_missing_summary(projects)


def _format_missing_fields_section(project: dict) -> list[dict]:
	"""Build Block Kit sections for the project's missing custom fields.

	Reuses the same field list as /pms missing-fields -- the audit is
	meant to be the one-stop report, so this shouldn't require a separate
	command to see.
	"""
	title = "📋 Missing Fields"
	missing = [
		(section_title, f"{icon} {label}")
		for section_title, fields in PROJECT_DETAIL_SECTIONS
		for fieldname, label, icon in fields
		if fieldname not in BOOLEAN_FIELDS and not project.get(fieldname)
	]

	if not missing:
		return [
			_header_block(title),
			{
				"type": "section",
				"text": {
					"type": "mrkdwn",
					"text": _quote("✅ All fields are filled in."),
				},
			},
		]

	blocks = [_header_block(f"{title} ({len(missing)} missing)")]
	rows = [
		[_raw_text_cell(section_title), _raw_text_cell(field)]
		for section_title, field in missing
	]
	blocks.append(_table_block(["SECTION", "FIELD"], rows))
	blocks.append(
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": _quote(
					"Tip: fill these in so future reports and audits are complete."
				),
			},
		},
	)
	return blocks


def _filter_projects(projects: list[dict], query: str) -> list[dict]:
	"""Filter projects by exact ID match or a case-insensitive name match."""
	query_lower = query.lower()
	return [
		p
		for p in projects
		if query_lower == p["name"].lower() or query_lower in p["project_name"].lower()
	]


def _format_multiple_matches(projects: list[dict], project_filter: str) -> str:
	"""Ask the user to narrow down when a filter matches more than one project."""
	matches = "\n".join(f"• *{p['project_name']}* · `{p['name']}`" for p in projects)
	return (
		f"🤷 '{project_filter}' matched {len(projects)} projects — "
		f"an audit needs exactly one. Use the exact project ID:\n{matches}"
	)


def _quote(text: str) -> str:
	"""Format advisory copy (tips/notes/empty-states) as a Slack blockquote."""
	return f"> {text}"


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
	"""Strip HTML tags from Frappe rich-text fields (e.g. ToDo.description).

	Also used for Risk.summary.
	"""
	return _HTML_TAG_RE.sub("", text).strip()


# Each bucket now renders as its own Slack block (see _format_task_section,
# _format_risk_section, _format_github_issues_section), so this can be
# raised well past what a single combined block could safely hold.
_MAX_AUDIT_ITEMS_PER_BUCKET = 15
_GITHUB_UPCOMING_WINDOW_DAYS = 7


def _categorize_tasks(tasks: list[dict]) -> dict[str, list[dict]]:
	"""Bucket Task records into overdue, no-deadline, upcoming, and done.

	"Overdue" and "no deadline" are computed directly from `exp_end_date`
	and `status` rather than trusted from Frappe's own "Overdue" status
	value, since that depends on a scheduled job having run recently.
	"""
	# Frappe's dates arrive naive (no tz info) -- treated as UTC, same
	# convention `to_unix` already uses elsewhere in this codebase, so both
	# sides of the comparison below stay timezone-aware and comparable.
	now = datetime.datetime.now(datetime.UTC)
	buckets: dict[str, list[dict]] = {
		"overdue": [],
		"no_deadline": [],
		"upcoming": [],
		"done": [],
	}

	for task in tasks:
		if task["status"] in TASK_CLOSED_STATUSES:
			buckets["done"].append(task)
			continue

		exp_end_date = task.get("exp_end_date")
		if not exp_end_date:
			buckets["no_deadline"].append(task)
		else:
			deadline = datetime.datetime.fromisoformat(exp_end_date).replace(
				tzinfo=datetime.UTC
			)
			if deadline < now:
				buckets["overdue"].append(task)
			else:
				buckets["upcoming"].append(task)

	buckets["overdue"].sort(key=lambda t: t["exp_end_date"])
	buckets["upcoming"].sort(key=lambda t: t["exp_end_date"])
	return buckets


def _debug_email_overrides() -> list[str]:
	"""Parse `PMS_DEBUG_EMAIL_OVERRIDE` into a list.

	Supports a single email or a comma-separated list (e.g.
	"a@rtcamp.com,b@rtcamp.com"), so testing can be scoped to a handful of
	people's projects instead of just one.
	"""
	raw = settings.PMS_DEBUG_EMAIL_OVERRIDE
	if not raw:
		return []
	return [email.strip() for email in raw.split(",") if email.strip()]


def _project_tab_url(project_id: str, tab: str) -> str:
	"""Build a link to a specific tab on the project's NextPMS page.

	Not a per-record deep link (no confirmed URL pattern exists for that
	in NextPMS) -- every row in a section links to the same project tab,
	which still gets a PM into the right context in one click.
	"""
	base = str(settings.FRAPPE_BASE_URL).rstrip("/")
	return f"{base}/next-pms/projects/{project_id}?tab={tab}"


def _header_block(text: str) -> dict:
	"""Build a Slack `header` block -- genuinely larger/bolder than section text.

	Unlike a section block's mrkdwn, header blocks are plain_text only (no
	`*bold*`/emoji-shortcode markup needed) and Slack renders them at a
	visibly bigger size, closer to a real heading.
	"""
	return {
		"type": "header",
		"text": {"type": "plain_text", "text": text, "emoji": True},
	}


def _raw_text_cell(text: str) -> dict:
	"""Build a plain-text table cell."""
	return {"type": "raw_text", "text": text}


def _link_cell(text: str, url: str) -> dict:
	"""Build a clickable table cell (rich_text with a link element)."""
	return {
		"type": "rich_text",
		"elements": [
			{
				"type": "rich_text_section",
				"elements": [{"type": "link", "url": url, "text": text}],
			},
		],
	}


def _table_block(header: list[str], rows: list[list[dict]]) -> dict:
	"""Build a Slack `table` block: real column alignment, with clickable link cells.

	Unlike a mrkdwn code block (the only other way to get column alignment),
	table cells support clickable rich_text links. The first column is set
	to wrap (titles are often long); other columns stay unwrapped since
	they're short (dates/status).
	"""
	header_row = [_raw_text_cell(h) for h in header]
	column_settings = [{"is_wrapped": True}] + [{} for _ in header[1:]]
	return {
		"type": "table",
		"rows": [header_row, *rows],
		"column_settings": column_settings,
	}


def _format_table_bucket(
	label: str, items: list, header: list[str], row_fn
) -> list[dict]:
	"""Build [label block, table block, optional overflow note] for one bucket.

	Shared by task, risk, and GitHub issue buckets. Capped at
	`_MAX_AUDIT_ITEMS_PER_BUCKET`; anything beyond that is called out as a
	blockquoted note below the table so nothing is silently dropped.
	"""
	if not items:
		return []

	shown = items[:_MAX_AUDIT_ITEMS_PER_BUCKET]
	rows = [row_fn(item) for item in shown]
	blocks = [
		{"type": "section", "text": {"type": "mrkdwn", "text": label}},
		_table_block(header, rows),
	]
	if len(items) > _MAX_AUDIT_ITEMS_PER_BUCKET:
		overflow = _quote(f"…and {len(items) - _MAX_AUDIT_ITEMS_PER_BUCKET} more")
		blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": overflow}})

	return blocks


_TASK_TABLE_HEADER = ["TITLE", "DUE", "STATUS"]


def _format_task_row(task: dict, status_icon: str, link_url: str) -> list[dict]:
	"""Build one task/todo table row: linked title, due date, status (icon + text).

	Deliberately omits Frappe's internal `name` (an opaque record ID with
	no meaning to a PM) -- the subject is the title people recognize.
	`status_icon` is supplied by the calling bucket (overdue/upcoming/no
	deadline aren't stored fields, so the bucket -- not the task -- knows
	which color applies); it lives once in the Status cell rather than
	repeating after every line of text. `link_url` opens the project's
	relevant NextPMS tab (no per-record deep link exists to jump straight
	to one task/todo).
	"""
	subject = task["subject"]
	if len(subject) > 70:
		subject = subject[:67] + "..."

	exp_end_date = task.get("exp_end_date")
	due = exp_end_date[:10] if exp_end_date else "—"

	return [
		_link_cell(subject, link_url),
		_raw_text_cell(due),
		_raw_text_cell(f"{status_icon} {task['status']}"),
	]


def _format_task_section(
	title: str,
	tasks: list[dict],
	link_url: str,
	llm_tip: str | None = None,
) -> list[dict]:
	"""Build Block Kit sections for a project's todos or milestones.

	Returns one label+table (+ optional overflow note) per populated
	bucket, so a large backlog can't overflow Slack's per-block limits even
	at a generous item cap. `link_url` is the project's relevant NextPMS
	tab, applied to every row's title. `llm_tip`, when present, replaces
	the hardcoded tip line(s) below with a single LLM-generated one; when
	absent (not requested, or the LLM call failed/had nothing to say), the
	hardcoded tips still run as a fallback so the section is never
	silently missing guidance. Returns `[]` (no header, nothing) when
	there's no data at all -- the whole section is omitted rather than
	shown as an empty placeholder.
	"""
	if not tasks:
		return []

	buckets = _categorize_tasks(tasks)
	blocks = [_header_block(f"{title} ({len(tasks)} total)")]

	# 🔴/🟡/⚪ are used consistently across every audit section: red = needs
	# action now, yellow = coming up, white = unknown/no data.
	bucket_specs = [
		("⚠️ *Overdue*", buckets["overdue"], "🔴"),
		("🗓️ *Upcoming (nearest deadline first)*", buckets["upcoming"], "🟡"),
		("❓ *No deadline set*", buckets["no_deadline"], "⚪"),
	]
	for label, bucket_tasks, icon in bucket_specs:
		blocks.extend(
			_format_table_bucket(
				label,
				bucket_tasks,
				_TASK_TABLE_HEADER,
				lambda t, icon=icon: _format_task_row(t, icon, link_url),
			),
		)

	tips = []
	if buckets["done"]:
		tips.append(_quote(f"✅ {len(buckets['done'])} completed/cancelled"))
	if llm_tip:
		tips.append(_quote(llm_tip))
	else:
		if buckets["overdue"]:
			tips.append(
				_quote(
					f"Tip: {len(buckets['overdue'])} item(s) are past their "
					"expected end date and still open — update status or push "
					"the date so reporting stays accurate.",
				),
			)
		if buckets["no_deadline"]:
			tips.append(
				_quote(
					f"Tip: {len(buckets['no_deadline'])} item(s) have no "
					"expected end date — add one so future audits can flag "
					"slippage risk.",
				),
			)
	if tips:
		blocks.append(
			{"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(tips)}}
		)

	return blocks


def _categorize_risks(risks: list[dict]) -> dict[str, list[dict]]:
	"""Bucket Risk records into blocked, open, and mitigated, by status."""
	buckets: dict[str, list[dict]] = {"blocked": [], "open": [], "mitigated": []}

	for risk in risks:
		if risk["status"] == RISK_BLOCKED_STATUS:
			buckets["blocked"].append(risk)
		elif risk["status"] == RISK_MITIGATED_STATUS:
			buckets["mitigated"].append(risk)
		else:
			buckets["open"].append(risk)

	buckets["open"].sort(key=lambda r: RISK_LEVEL_ORDER.get(r["risk_level"], 99))
	return buckets


_RISK_LEVEL_ICON = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}


_RISK_TABLE_HEADER = ["SUMMARY", "CATEGORY", "LEVEL", "STATUS"]


def _format_risk_row(risk: dict, link_url: str) -> list[dict]:
	"""Build one risk table row: linked summary, category, level (icon + text), status.

	Risk has no title field in Frappe -- `summary` (rich text) is the
	closest thing to one, so it's cleaned and truncated for that role
	rather than showing the meaningless internal record `name`. The level
	icon reflects `risk_level` (an inherent property of the risk itself,
	unlike task/GitHub buckets), so it stays meaningful even within the
	"Open" bucket where levels are mixed -- it lives in its own column
	rather than repeating after every row's text. `link_url` opens the
	project's Risks tab (no per-record deep link exists).
	"""
	summary = _strip_html(risk.get("summary") or "") or "(no summary)"
	if len(summary) > 70:
		summary = summary[:67] + "..."

	icon = _RISK_LEVEL_ICON.get(risk["risk_level"], "⚪")
	return [
		_link_cell(summary, link_url),
		_raw_text_cell(risk.get("risk_category") or "—"),
		_raw_text_cell(f"{icon} {risk['risk_level']}"),
		_raw_text_cell(risk["status"]),
	]


def _format_risk_section(
	risks: list[dict], link_url: str, llm_tip: str | None = None
) -> list[dict]:
	"""Build Block Kit sections for a project's risks.

	Risks have no due-date field in Frappe, so they're grouped by status
	and, within "open", sorted by risk level rather than by deadline.
	Returns one label+table (+ optional overflow note) per populated
	bucket, matching `_format_task_section`. `link_url` is the project's
	Risks tab, applied to every row. `llm_tip` behaves the same way:
	replaces the hardcoded tip when present, otherwise the hardcoded
	fallback still runs. Returns `[]` when there's no data at all -- the
	whole section is omitted rather than shown as an empty placeholder.
	"""
	title = "🚨 Risks"
	if not risks:
		return []

	buckets = _categorize_risks(risks)
	blocks = [_header_block(f"{title} ({len(risks)} total)")]

	blocks.extend(
		_format_table_bucket(
			"🚫 *Blocked*",
			buckets["blocked"],
			_RISK_TABLE_HEADER,
			lambda r: _format_risk_row(r, link_url),
		),
	)

	# No static color on this label -- levels are mixed within "Open" and
	# each row's own Level column (from _format_risk_row) already shows it.
	blocks.extend(
		_format_table_bucket(
			"*Open (highest risk level first)*",
			buckets["open"],
			_RISK_TABLE_HEADER,
			lambda r: _format_risk_row(r, link_url),
		),
	)

	tips = [
		_quote(
			"Note: risks don't carry a due date in Frappe, so they're prioritized by "
			"level instead of deadline.",
		),
	]
	if buckets["mitigated"]:
		tips.append(_quote(f"✅ {len(buckets['mitigated'])} mitigated"))
	if llm_tip:
		tips.append(_quote(llm_tip))
	elif buckets["blocked"]:
		tips.append(
			_quote(
				f"Tip: {len(buckets['blocked'])} risk(s) are blocked — these need "
				"escalation before they impact the timeline.",
			),
		)
	blocks.append(
		{"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(tips)}}
	)

	return blocks


# Statuses where a missing target date is expected, not a problem -- these
# are pre-work queue states, so an undated issue here isn't flagged under
# "No target date set" (it'd just be noise); it's folded into "later"
# instead, so it's still counted but not treated as something to act on.
_NO_DATE_EXPECTED_STATUSES = {"backlog", "ready for deployment", "to do", "todo"}


def _categorize_github_issues(issues: list[dict]) -> dict[str, list[dict]]:
	"""Bucket open GitHub issues into blocked, fast-pending, upcoming, and undated.

	`status` is the Projects V2 board's Status field, so `blocked` is
	checked first regardless of dates, mirroring `_categorize_risks`.
	`target_date` is that board's "Target date" field, not GitHub's
	native issue milestone.
	"""
	now = datetime.datetime.now(datetime.UTC).date()
	soon = now + datetime.timedelta(days=_GITHUB_UPCOMING_WINDOW_DAYS)
	buckets: dict[str, list[dict]] = {
		"blocked": [],
		"fast_pending": [],
		"future_week": [],
		"no_date": [],
		"later": [],
	}

	for issue in issues:
		if issue.get("status") == BLOCKED_ISSUE_STATUS_NAME:
			buckets["blocked"].append(issue)
			continue

		target_date = issue.get("target_date")
		if not target_date:
			status = (issue.get("status") or "").strip().lower()
			if status in _NO_DATE_EXPECTED_STATUSES:
				buckets["later"].append(issue)
			else:
				buckets["no_date"].append(issue)
			continue

		due = datetime.date.fromisoformat(target_date)
		if due < now:
			buckets["fast_pending"].append(issue)
		elif due <= soon:
			buckets["future_week"].append(issue)
		else:
			buckets["later"].append(issue)

	buckets["fast_pending"].sort(key=lambda i: i["target_date"])
	buckets["future_week"].sort(key=lambda i: i["target_date"])
	return buckets


_GITHUB_TABLE_HEADER = ["TITLE", "START", "END", "STATUS"]


def _format_github_row(issue: dict, status_icon: str) -> list[dict]:
	"""Build one GitHub issue table row: clickable title, start date, end date, status.

	The Title cell is a real clickable link (table cells support rich_text
	link elements, unlike mrkdwn code-block tables). Start/end get their
	own columns rather than one combined "timeline" string, so they line
	up and are scannable independent of title length. `status_icon` is
	supplied by the calling bucket, same reasoning as `_format_task_row`
	(blocked/overdue/upcoming/no-date isn't a stored field on the issue).
	"""
	title = issue["title"]
	if len(title) > 70:
		title = title[:67] + "..."
	title_cell = _link_cell(f"#{issue['number']} {title}", issue["url"])

	start_date = issue.get("start_date") or "—"
	target_date = issue.get("target_date") or "—"
	status = issue.get("status") or "—"
	return [
		title_cell,
		_raw_text_cell(start_date),
		_raw_text_cell(target_date),
		_raw_text_cell(f"{status_icon} {status}"),
	]


def _format_github_issues_section(
	issues: list[dict], llm_tip: str | None = None
) -> list[dict]:
	"""Build Block Kit sections for a project's open GitHub issues.

	Bucketed by the board's Status/Target date fields rather than GitHub's
	native milestone, since that's what's actually set on these boards.
	Issues with no Status value at all aren't properly triaged on the
	board, so they're excluded entirely rather than shown in a possibly
	misleading bucket -- the "(N open)" count below reflects only the
	issues actually being categorized, not the raw fetched total, so the
	numbers on screen always add up. Returns one label+table (+ optional
	overflow note) per populated bucket, since a busy repo can have every
	bucket near the item cap at once. `llm_tip` behaves as in
	`_format_task_section`. Returns `[]` when there are no open,
	status-tagged issues at all -- the whole section is omitted rather
	than shown as an empty placeholder.
	"""
	title = "🐙 GitHub Issues"
	issues = [issue for issue in issues if issue.get("status")]
	if not issues:
		return []

	buckets = _categorize_github_issues(issues)
	blocks = [_header_block(f"{title} ({len(issues)} open)")]

	# Same 🔴/🟡/⚪ convention as tasks: red = needs action now (blocked or
	# overdue), yellow = coming up, white = unknown/no date set.
	bucket_specs = [
		("🚫 *Blocked*", buckets["blocked"], "🔴"),
		("⏰ *Overdue (target date passed)*", buckets["fast_pending"], "🔴"),
		(
			f"📅 *Upcoming (due within {_GITHUB_UPCOMING_WINDOW_DAYS} days)*",
			buckets["future_week"],
			"🟡",
		),
		("❓ *No target date set*", buckets["no_date"], "⚪"),
	]
	for label, bucket_issues, icon in bucket_specs:
		blocks.extend(
			_format_table_bucket(
				label,
				bucket_issues,
				_GITHUB_TABLE_HEADER,
				lambda i, icon=icon: _format_github_row(i, icon),
			),
		)

	tips = []
	if buckets["later"]:
		tips.append(
			_quote(
				f"{len(buckets['later'])} due later than "
				f"{_GITHUB_UPCOMING_WINDOW_DAYS} days out"
			),
		)
	if llm_tip:
		tips.append(_quote(llm_tip))
	else:
		if buckets["fast_pending"]:
			tips.append(
				_quote(
					f"Tip: {len(buckets['fast_pending'])} issue(s) are past "
					"their target date and still open — update the board or "
					"push the date so this stays accurate.",
				),
			)
		if buckets["no_date"]:
			tips.append(
				_quote(
					f"Tip: {len(buckets['no_date'])} issue(s) have no target "
					"date set on the board — add one so future audits can "
					"flag slippage risk.",
				),
			)
	if tips:
		blocks.append(
			{"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(tips)}}
		)

	return blocks


def _format_audit_header(
	project: dict,
	project_detail: dict,
	github_repos: list[dict],
) -> list[dict]:
	"""Build the audit's header blocks: project identity, RAG status, GitHub link."""
	blocks = [_header_block(f"🗂️ Audit: {project['project_name']}")]

	lines = [f"`{project['name']}` · {project['status']}"]

	rag_status = project_detail.get("custom_project_rag_status")
	if rag_status:
		rag_icon = {"Green": "🟢", "Amber": "🟠", "Red": "🔴"}.get(rag_status, "⚪")
		lines.append(f"RAG status: *{rag_status}* {rag_icon}")

	if github_repos:
		repo_list = ", ".join(
			f"`{r['repository_owner']}/{r['repository_name']}`" for r in github_repos
		)
		lines.append(f"🔌 GitHub: {repo_list}")
	else:
		lines.append(
			_quote("⚠️ No GitHub repository connected to this project in Frappe.")
		)

	blocks.append(
		{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
	)
	return blocks


def _normalize_todo(todo: dict) -> dict:
	"""Normalize a standalone ToDo record into the Task-like shape formatters expect."""
	status = todo.get("status") or ""
	description = _strip_html(todo.get("description") or "") or "(no description)"
	return {
		"name": todo["name"],
		"subject": description,
		"status": TODO_STATUS_TO_TASK_STATUS.get(status, status),
		"is_milestone": 0,
		"exp_end_date": todo.get("date"),
	}


def _normalize_pti_milestone(pti: dict) -> dict:
	"""Normalize a Project Timeline Item (type=Milestone) into a Task-like shape.

	PTI uses different field names from Task: `title` instead of `subject`,
	`planned_end_date` instead of `exp_end_date`, and `is_complete` (0/1)
	instead of a `status` string. We derive a status string so the existing
	`_format_task_section` / `_categorize_tasks` logic works unchanged:
	- `actual_end_date` set → "Completed" (it was actually finished)
	- `is_complete=1` but no actual end date → "Completed"
	- otherwise → "Open"
	"""
	if pti.get("actual_end_date") or pti.get("is_complete"):
		status = "Completed"
	else:
		status = "Open"
	return {
		"name": pti["name"],
		"subject": pti.get("title") or "(untitled milestone)",
		"status": status,
		"is_milestone": 1,
		"exp_end_date": pti.get("planned_end_date"),
	}


def _format_audit_report(
	project: dict,
	project_detail: dict,
	milestones: list[dict],
	todos: list[dict],
	risks: list[dict],
	github_repos: list[dict],
	github_issues: list[dict] | None,
	tips: dict,
) -> tuple[str, list[dict]]:
	"""Build the /pms audit response as fallback text plus Block Kit blocks.

	`github_issues` is `None` when repos are connected but the GitHub API
	call itself failed (as opposed to `[]`, which means it succeeded and
	found nothing) -- these render as a distinct "couldn't fetch" section
	so a transient GitHub outage doesn't get mistaken for "no open issues"
	(genuinely zero issues still omits the section like everything else).
	`tips` holds LLM-generated copy (`milestonesTip`/`todosTip`/`risksTip`/
	`githubTip`, any of which may be absent) -- empty dict falls back to
	hardcoded tips.

	Each section (Milestones/Todos/Risks/GitHub Issues) is entirely
	omitted -- no header, no placeholder text -- when it has no data at
	all, rather than shown as an empty section. Dividers are only inserted
	between sections that actually rendered something, so an omitted
	section never leaves a stray or doubled-up divider behind.
	"""
	project_id = project["name"]

	github_section: list[dict] = []
	if github_repos:
		if github_issues is None:
			github_section = [
				_header_block("🐙 GitHub Issues"),
				{
					"type": "section",
					"text": {
						"type": "mrkdwn",
						"text": _quote("⚠️ Could not fetch GitHub issues right now."),
					},
				},
			]
		else:
			github_section = _format_github_issues_section(
				github_issues, tips.get("githubTip")
			)

	sections = [
		list(_format_audit_header(project, project_detail, github_repos)),
		_format_missing_fields_section(project),
		_format_task_section(
			"📌 Milestones",
			milestones,
			_project_tab_url(project_id, "calendar"),
			tips.get("milestonesTip"),
		),
		_format_task_section(
			"✅ Todos",
			todos,
			_project_tab_url(project_id, "to-do"),
			tips.get("todosTip"),
		),
		_format_risk_section(
			risks, _project_tab_url(project_id, "risks"), tips.get("risksTip")
		),
		github_section,
		[
			{
				"type": "context",
				"elements": [
					{
						"type": "mrkdwn",
						"text": (
							"_Pulled live from Frappe. Re-run `/pms audit` "
							"after updating records to refresh this report._"
						),
					},
				],
			},
		],
	]

	blocks: list[dict] = []
	for section in sections:
		if not section:
			continue
		if blocks:
			blocks.append({"type": "divider"})
		blocks.extend(section)

	fallback_text = f"🗂️ Audit for {project['project_name']} ({project['name']})"
	return fallback_text, blocks


def _strip_ids(items: list[dict]) -> list[dict]:
	"""Drop the internal Frappe record `name` before sending data to the LLM.

	It's an opaque record ID with no meaning outside Frappe, and including
	it led the LLM to echo it back as if it were a title.
	"""
	return [{k: v for k, v in item.items() if k != "name"} for item in items]


async def _generate_audit_tips(
	ctx: inngest.Context,
	project: dict,
	milestones: list[dict],
	todos: list[dict],
	risks: list[dict],
	github_issues: list[dict] | None,
) -> dict:
	"""Generate business-value-framed tips via LLM.

	Returns `{}` on any failure (unreachable Langfuse prompt, LLM error,
	timeout, etc.) so callers fall back to the hardcoded per-section tips
	rather than breaking the audit.
	"""
	# Lazy import: app.llm.inngest already imports from app.slack.inngest
	# (main.py -> fetch_slack), so importing this at module load time here
	# would risk a circular import depending on which package initializes
	# first. By call time all modules are already fully loaded.
	from app.llm.inngest.audit_tips import generate_audit_tips

	audit_data = {
		"project_name": project["project_name"],
		# `name` (Frappe's internal, opaque record ID) is dropped -- it's
		# meaningless to the LLM and was leaking into generated tips
		# (e.g. "(63v7bnelc5)") instead of a real title.
		"milestones": _strip_ids(milestones),
		"todos": _strip_ids(todos),
		"risks": _strip_ids(risks),
		"github_issues": github_issues or [],
	}
	try:
		return await ctx.step.invoke(
			"generate_audit_tips",
			function=generate_audit_tips,
			data={"audit_data": audit_data},
		)
	except Exception as exc:
		logger.warning("Error generating audit tips for %s: %s", project["name"], exc)
		return {}


async def _build_audit_report(
	ctx: inngest.Context,
	frappe_service: FrappeService,
	project: dict,
) -> tuple[str, list[dict]]:
	"""Fetch a project's milestones, todos, risks, and GitHub links, then format them.

	Milestone priority:
	1. Project Timeline Item (type=Milestone) -- the real source that
		powers ?tab=calendar in Next PMS.
	2. Task records with is_milestone=1 -- legacy fallback for older
		projects that predate the PTI doctype.
	Whichever source returns records is used exclusively; both are never
	combined (they'd produce duplicates).
	"""
	project_id = project["name"]
	(
		project_detail,
		pti_milestones,
		tasks,
		standalone_todos,
		risks,
	) = await asyncio.gather(
		frappe_service.get_project_by_id(project_id),
		frappe_service.get_milestones_by_project(project_id),
		frappe_service.get_tasks_by_project(project_id),
		frappe_service.get_todos_by_project(project_id),
		frappe_service.get_risks_by_project(project_id),
	)
	project_detail = project_detail or {}

	# Use PTI milestones if any exist; fall back to Task.is_milestone records.
	if pti_milestones:
		milestones = [_normalize_pti_milestone(pti) for pti in pti_milestones]
		todos = [task for task in tasks if not task.get("is_milestone")] + [
			_normalize_todo(todo) for todo in standalone_todos
		]
	else:
		milestones = [task for task in tasks if task.get("is_milestone")]
		todos = [task for task in tasks if not task.get("is_milestone")] + [
			_normalize_todo(todo) for todo in standalone_todos
		]

	connections = project_detail.get("custom_project_repository_connections") or []
	repo_names = [
		c["github_repository"] for c in connections if c.get("github_repository")
	]
	github_repos = await frappe_service.get_github_repositories(repo_names)

	github_issues: list[dict] | None = []
	if github_repos:
		try:
			github_issues = await GitHubDataService().fetch_open_issues_for_audit(
				[(r["repository_owner"], r["repository_name"]) for r in github_repos],
			)
		except Exception as exc:
			logger.warning("Error fetching GitHub issues for %s: %s", project_id, exc)
			github_issues = None

	tips = await _generate_audit_tips(
		ctx, project, milestones, todos, risks, github_issues
	)

	return _format_audit_report(
		project,
		project_detail,
		milestones,
		todos,
		risks,
		github_repos,
		github_issues,
		tips,
	)


@inngest_client.create_function(
	fn_id="handle_pms_command",
	trigger=inngest.TriggerEvent(event="rt-report-automation/pms_command"),
	retries=2,
)
async def handle_pms_command(ctx: inngest.Context):
	"""Inngest function to handle the Slack /pms slash command.

	Resolves the requesting Slack user's email (or uses
	`settings.PMS_DEBUG_EMAIL_OVERRIDE` if set, for local testing), looks up
	their Frappe PMS projects by matching that email against the project
	manager field, and replies via the slash command's `response_url` with
	the project list, a missing-fields report, or a full per-project audit.

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

	debug_emails = _debug_email_overrides()
	if debug_emails:
		# A single slash-command invocation has one caller -- if multiple
		# debug emails are configured (for the bulk-audit override), just
		# use the first for this per-user command flow.
		email = debug_emails[0]
	else:
		notifier = SlackNotifierService()
		email = notifier.get_user_email(user_id)

	blocks: list[dict] | None = None

	if not email:
		text = "Couldn't resolve your email from your Slack profile."
	else:
		frappe_service = FrappeService()
		projects = await frappe_service.get_projects_by_manager_email(email)

		if project_filter:
			projects = _filter_projects(projects, str(project_filter))

		if project_filter and not projects:
			text = (
				f"🤷 No project matching '{project_filter}' found among your projects."
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

	payload: dict[str, object] = {
		"response_type": "in_channel",
		"text": text,
		"replace_original": True,
	}
	if blocks:
		payload["blocks"] = blocks

	async with httpx.AsyncClient() as client:
		await client.post(response_url, json=payload)


async def _send_project_audit(email: str, text: str, blocks: list[dict]) -> dict:
	"""Deliver one project's audit via Slack DM.

	Deliberately calls no `ctx.step.*` methods -- the caller wraps this in
	`ctx.step.run` so a function retry never re-sends an already-delivered
	audit, and nesting another step call inside a `ctx.step.run` handler
	isn't something the installed Inngest SDK is confirmed to support
	(it ships a dedicated `NestedStepInterrupt` for exactly this).

	Returns:
		dict: `{"delivered": bool}` -- JSON-serializable, as required for
			a `ctx.step.run` handler's return value.

	"""
	notifier = SlackNotifierService()
	delivered = notifier.send_message(email, text, blocks)
	return {"delivered": delivered}


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
	project = ctx.event.data["project"]
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

	Returns:
		dict: `{"total": int, "sent": int, "skipped": int}` summary.

	"""

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
	# NOTE: remove this override before the real production rollout. Reuses
	# the existing PMS_DEBUG_EMAIL_OVERRIDE setting (same one handle_pms_command
	# already uses) to scope test runs to a handful of people's projects
	# instead of every billable project at the company. If this is ever left
	# set in a real deployment, it would silently limit every future
	# bulk-audit run to just these emails, not just the test run.
	projects = await frappe_service.get_billable_open_projects(
		manager_emails=_debug_email_overrides() or None,
	)

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
