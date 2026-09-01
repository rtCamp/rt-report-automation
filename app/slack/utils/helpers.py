"""Formatting, categorization, and orchestration helpers for the /pms Slack bot.

Everything here is private (leading underscore) and used only by the four
Inngest-triggered entry points in `app.slack.inngest.slack` -- kept in its
own module so that file stays limited to the actual Inngest function
definitions rather than ~1400 lines of Block Kit formatting logic.
"""

import asyncio
import datetime
import logging
import re

import inngest

from app.core.config import settings
from app.frappe.constants import (
	BOOLEAN_FIELDS,
	DELIVERY_MANAGER_ROLE,
	PROJECT_BILLING_TYPE_FIELD,
	PROJECT_BUDGET_FIELD,
	PROJECT_DETAIL_FIELDS,
	PROJECT_DETAIL_SECTIONS,
	PROJECT_ENGINEERING_MANAGER_FIELD,
	PROJECT_MANAGER_FIELD,
	PROJECT_SUPPRESSED_STATUSES,
	RETAINER_BILLING_TYPE,
	RISK_BLOCKED_STATUS,
	RISK_LEVEL_ORDER,
	RISK_MITIGATED_STATUS,
	TASK_CLOSED_STATUSES,
	TODO_STATUS_TO_TASK_STATUS,
)
from app.frappe.service import FrappeService
from app.github.services.github_data import GitHubDataService
from app.github.utils.constants import BLOCKED_ISSUE_STATUS_NAME
from app.slack.notifier import SlackNotifierService

logger = logging.getLogger(__name__)


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
		{"type": "text", "text": f"  ·  {total} total\n\n"},
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
		status_icon = _STATUS_ICONS.get(p["status"], "⚪")
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
	blocks.append(_open_overview_button(project["name"]))
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


# Each bucket now renders as its own Slack block (see _format_todo_section,
# _format_risk_section, _format_github_issues_section), so this can be
# raised well past what a single combined block could safely hold.
_MAX_AUDIT_ITEMS_PER_BUCKET = 15
_GITHUB_UPCOMING_WINDOW_DAYS = 7
_TODO_UPCOMING_WINDOW_DAYS = 7


def _categorize_todos(tasks: list[dict]) -> dict[str, list[dict]]:
	"""Bucket Task/ToDo records into overdue, upcoming, later, no-deadline, and done.

	"Overdue" and "no deadline" are computed directly from `exp_end_date`
	and `status` rather than trusted from Frappe's own "Overdue" status
	value, since that depends on a scheduled job having run recently.
	"Upcoming" is scoped to `_TODO_UPCOMING_WINDOW_DAYS` (matching the
	Monday audit cadence) -- anything further out lands in "later" so
	nothing is silently dropped, mirroring `_categorize_github_issues`.
	"""
	# `exp_end_date` is a date-only Frappe field (no time component) --
	# compared as calendar dates, not datetimes, so an item due today isn't
	# marked overdue for most of the day it's actually still due.
	today = datetime.datetime.now(datetime.UTC).date()
	soon = today + datetime.timedelta(days=_TODO_UPCOMING_WINDOW_DAYS)
	buckets: dict[str, list[dict]] = {
		"overdue": [],
		"no_deadline": [],
		"upcoming": [],
		"later": [],
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
			deadline = datetime.date.fromisoformat(exp_end_date[:10])
			if deadline < today:
				buckets["overdue"].append(task)
			elif deadline <= soon:
				buckets["upcoming"].append(task)
			else:
				buckets["later"].append(task)

	buckets["overdue"].sort(key=lambda t: t["exp_end_date"])
	buckets["upcoming"].sort(key=lambda t: t["exp_end_date"])
	return buckets


def _project_tab_url(project_id: str, tab: str) -> str:
	"""Build a link to a specific tab on the project's NextPMS page.

	Not a per-record deep link (no confirmed URL pattern exists for that
	in NextPMS) -- every row in a section links to the same project tab,
	which still gets a PM into the right context in one click.
	"""
	base = str(settings.FRAPPE_BASE_URL).rstrip("/")
	return f"{base}/next-pms/projects/{project_id}?tab={tab}"


def _project_overview_url(project_id: str) -> str:
	"""Build a link to the project's overview page (no specific tab) in Next PMS."""
	base = str(settings.FRAPPE_BASE_URL).rstrip("/")
	return f"{base}/next-pms/projects/{project_id}"


def _link_button(text: str, url: str, action_id: str) -> dict:
	"""Build an `actions` block with a single button linking out to `url`."""
	return {
		"type": "actions",
		"elements": [
			{
				"type": "button",
				"text": {"type": "plain_text", "text": text, "emoji": True},
				"url": url,
				"action_id": action_id,
			}
		],
	}


def _open_overview_button(project_id: str) -> dict:
	"""Build an `actions` block with a button linking to the project overview page."""
	return _link_button(
		"🔗 Open Project Overview",
		_project_overview_url(project_id),
		"open_project_overview",
	)


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


def _format_todo_section(
	title: str,
	tasks: list[dict],
	link_url: str,
	llm_tip: str | None = None,
	milestones: list[dict] | None = None,
) -> list[dict]:
	"""Build Block Kit sections for a project's todos.

	Returns one label+table (+ optional overflow note) per populated
	bucket, so a large backlog can't overflow Slack's per-block limits even
	at a generous item cap. `link_url` is the project's relevant NextPMS
	tab, applied to every row's title. `llm_tip`, when present, replaces
	the hardcoded tip line(s) below with a single LLM-generated one; when
	absent (not requested, or the LLM call failed/had nothing to say), the
	hardcoded tips still run as a fallback so the section is never
	silently missing guidance. Returns `[]` (no header, nothing) when
	there's no data at all -- the whole section is omitted rather than
	shown as an empty placeholder -- *unless* `milestones` has one still
	open, in which case the section still renders (with a 0 count) just to
	carry a nudge to add a todo for that milestone, since silence there
	would read as "nothing to track" rather than "untracked work."
	"""
	if not tasks:
		if milestones and any(
			m["status"] not in TASK_CLOSED_STATUSES for m in milestones
		):
			return [
				_header_block(f"{title} (0 total)"),
				{
					"type": "section",
					"text": {
						"type": "mrkdwn",
						"text": _quote(
							"💡 There's an open milestone but no todos tracked for "
							"this project — consider adding one to break it down "
							"into actionable steps."
						),
					},
				},
				_link_button("➕ Add Todo", link_url, "add_todo_for_milestone"),
			]
		return []

	buckets = _categorize_todos(tasks)
	blocks = [_header_block(f"{title} ({len(tasks)} total)")]

	# 🔴/🟡/⚪ are used consistently across every audit section: red = needs
	# action now, yellow = coming up, white = unknown/no data.
	bucket_specs = [
		("⚠️ *Overdue*", buckets["overdue"], "🔴"),
		(
			f"🗓️ *Upcoming (within {_TODO_UPCOMING_WINDOW_DAYS} days)*",
			buckets["upcoming"],
			"🟡",
		),
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
	if buckets["later"]:
		tips.append(
			_quote(
				f"{len(buckets['later'])} due later than "
				f"{_TODO_UPCOMING_WINDOW_DAYS} days out"
			),
		)
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


# Milestones due further out than this aren't actionable yet, so they're
# suppressed from the "upcoming" bucket rather than shown/flagged.
_MILESTONE_SUPPRESS_DAYS = 365


def _categorize_milestones(milestones: list[dict]) -> dict[str, list[dict]]:
	"""Bucket milestones into overdue-but-open, upcoming, far-out, no-deadline, done.

	Unlike todos, a milestone whose planned completion date has already
	passed while still marked incomplete ("overdue_open") is escalated as
	its own bucket rather than folded into a generic overdue list -- a
	stronger signal for a retainer than a todo running late. Anything due
	more than `_MILESTONE_SUPPRESS_DAYS` out is suppressed into "far_out"
	rather than shown as upcoming, since it isn't actionable yet.
	"""
	# `exp_end_date` is a date-only Frappe field -- compared as calendar
	# dates, not datetimes, so a milestone due today isn't marked overdue
	# for most of the day it's actually still due.
	today = datetime.datetime.now(datetime.UTC).date()
	horizon = today + datetime.timedelta(days=_MILESTONE_SUPPRESS_DAYS)
	buckets: dict[str, list[dict]] = {
		"overdue_open": [],
		"upcoming": [],
		"far_out": [],
		"no_deadline": [],
		"done": [],
	}

	for milestone in milestones:
		if milestone["status"] in TASK_CLOSED_STATUSES:
			buckets["done"].append(milestone)
			continue

		exp_end_date = milestone.get("exp_end_date")
		if not exp_end_date:
			buckets["no_deadline"].append(milestone)
		else:
			deadline = datetime.date.fromisoformat(exp_end_date[:10])
			if deadline < today:
				buckets["overdue_open"].append(milestone)
			elif deadline <= horizon:
				buckets["upcoming"].append(milestone)
			else:
				buckets["far_out"].append(milestone)

	buckets["overdue_open"].sort(key=lambda m: m["exp_end_date"])
	buckets["upcoming"].sort(key=lambda m: m["exp_end_date"])
	return buckets


def _has_milestone_in_month_window(milestones: list[dict]) -> bool:
	"""Check whether any milestone (any status) lands in the current or next month.

	Flags a retainer coverage gap, not a per-item overdue/upcoming
	condition, so it's checked across the full unfiltered list rather than
	one of `_categorize_milestones`'s buckets.
	"""
	now = datetime.datetime.now(datetime.UTC).date()
	next_month = now.month + 1
	next_year = now.year
	if next_month > 12:
		next_month = 1
		next_year += 1
	month_year_pairs = {(now.year, now.month), (next_year, next_month)}

	for milestone in milestones:
		exp_end_date = milestone.get("exp_end_date")
		if not exp_end_date:
			continue
		due = datetime.date.fromisoformat(exp_end_date[:10])
		if (due.year, due.month) in month_year_pairs:
			return True
	return False


def _format_milestone_section(
	milestones: list[dict],
	link_url: str,
	*,
	is_retainer: bool,
	llm_tip: str | None = None,
) -> list[dict]:
	"""Build Block Kit sections for a project's milestones.

	Milestones get their own bucketing (see `_categorize_milestones`)
	rather than reusing the todo one: a completion date that's passed while
	still marked Open is escalated separately, and anything due more than
	`_MILESTONE_SUPPRESS_DAYS` out is suppressed rather than shown. For
	retainer projects (`is_retainer`), also flags when no milestone at all
	lands in the current or next calendar month -- a coverage gap that
	matters even when `milestones` is empty, so (unlike every other audit
	section) this doesn't return `[]` just because there's no data, when
	the project is a retainer.
	"""
	title = "📌 Milestones"
	if not milestones:
		if is_retainer:
			return [
				_header_block(title),
				{
					"type": "section",
					"text": {
						"type": "mrkdwn",
						"text": _quote(
							"⚠️ No milestones exist for this retainer project -- "
							"nothing scheduled for this month or next."
						),
					},
				},
				_link_button("➕ Add Milestone", link_url, "add_milestone"),
			]
		return []

	buckets = _categorize_milestones(milestones)
	blocks = [_header_block(f"{title} ({len(milestones)} total)")]

	if is_retainer and not _has_milestone_in_month_window(milestones):
		blocks.append(
			{
				"type": "section",
				"text": {
					"type": "mrkdwn",
					"text": _quote(
						"⚠️ No milestone scheduled for this month or next month."
					),
				},
			},
		)

	bucket_specs = [
		("⏰ *Completion date passed, still open*", buckets["overdue_open"], "🔴"),
		(
			f"🗓️ *Upcoming (within {_MILESTONE_SUPPRESS_DAYS} days)*",
			buckets["upcoming"],
			"🟡",
		),
		("❓ *No deadline set*", buckets["no_deadline"], "⚪"),
	]
	for label, bucket_milestones, icon in bucket_specs:
		blocks.extend(
			_format_table_bucket(
				label,
				bucket_milestones,
				_TASK_TABLE_HEADER,
				lambda m, icon=icon: _format_task_row(m, icon, link_url),
			),
		)

	tips = []
	if buckets["done"]:
		tips.append(_quote(f"✅ {len(buckets['done'])} completed"))
	if buckets["far_out"]:
		tips.append(
			_quote(
				f"{len(buckets['far_out'])} due more than "
				f"{_MILESTONE_SUPPRESS_DAYS} days out"
			),
		)
	if llm_tip:
		tips.append(_quote(llm_tip))
	elif buckets["overdue_open"]:
		tips.append(
			_quote(
				f"Tip: {len(buckets['overdue_open'])} milestone(s) have passed "
				"their planned completion date and are still open — mark "
				"them complete or push the date so reporting stays accurate.",
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
	bucket, matching `_format_todo_section`. `link_url` is the project's
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
			"Note: risks don't carry a due date in Next PMS, so they're prioritized by "
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
	`_format_todo_section`. Returns `[]` when there are no open,
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


# Retainer/budget-burn thresholds: escalate hours consumed above 80% any
# time before cycle close, and budget burn more than 20 points ahead of
# schedule burn.
_RETAINER_HOURS_CONSUMED_THRESHOLD = 80
_BUDGET_BURN_AHEAD_THRESHOLD = 20


def _current_budget_cycle(budget_rows: list[dict]) -> dict | None:
	"""Pick the `Project Budget` cycle to evaluate: today's, or the latest past one.

	`Project Budget` rows are a child table on Project (field
	`custom_project_budget_hours`) -- they arrive nested in the full
	project document from `get_project_by_id`, no separate fetch needed.
	"""
	if not budget_rows:
		return None

	today = datetime.datetime.now(datetime.UTC).date()
	for row in budget_rows:
		start, end = row.get("start_date"), row.get("end_date")
		if not start or not end:
			continue
		start_date = datetime.date.fromisoformat(start)
		end_date = datetime.date.fromisoformat(end)
		if start_date <= today <= end_date:
			return row

	# No cycle covers today -- fall back to the most recently *closed* one
	# (end_date in the past), never a not-yet-started future cycle, which
	# would otherwise hide the real closed cycle's unbilled-hours warning.
	past = [
		row
		for row in budget_rows
		if row.get("end_date") and datetime.date.fromisoformat(row["end_date"]) < today
	]
	return max(past, key=lambda row: row["end_date"]) if past else None


def _format_budget_section(project_detail: dict, *, is_retainer: bool) -> list[dict]:
	"""Flag retainer hours-consumed and budget burn running ahead of schedule.

	"Schedule burn" is approximated as elapsed time within the cycle's
	start/end dates -- no task-completion-based measure of schedule
	progress exists yet, so this is an assumption to revisit with the ERP
	owner if a different definition is wanted. Returns `[]` when the
	project has no `Project Budget` cycle to evaluate at all.
	"""
	cycle = _current_budget_cycle(project_detail.get(PROJECT_BUDGET_FIELD) or [])
	if not cycle:
		return []

	hours_purchased = cycle.get("hours_purchased") or 0
	if hours_purchased <= 0:
		return []
	consumed_hours = cycle.get("consumed_hours") or 0
	remaining_hours = cycle.get("remaining_hours")
	if remaining_hours is None:
		remaining_hours = hours_purchased - consumed_hours
	consumed_pct = consumed_hours / hours_purchased * 100

	today = datetime.datetime.now(datetime.UTC).date()
	start_date = cycle.get("start_date")
	end_date = cycle.get("end_date")
	start = datetime.date.fromisoformat(start_date) if start_date else None
	end = datetime.date.fromisoformat(end_date) if end_date else None

	lines = [
		(
			f"⏱️ Hours consumed this cycle: "
			f"*{consumed_hours:.1f} / {hours_purchased:.1f}* "
			f"({consumed_pct:.0f}%)"
		)
	]

	if is_retainer and end:
		days_left = (end - today).days
		if consumed_pct > _RETAINER_HOURS_CONSUMED_THRESHOLD and today <= end:
			lines.append(
				_quote(
					f"🔴 {consumed_pct:.0f}% of this cycle's hours are consumed with "
					f"{days_left} day(s) still left in the cycle."
				),
			)
		if today > end and remaining_hours > 0 and not cycle.get("sales_invoice"):
			lines.append(
				_quote(
					f"🔴 Cycle closed on {cycle['end_date']} with "
					f"{remaining_hours:.1f} unbilled hour(s) remaining and no linked "
					"sales invoice."
				),
			)

	if start and end and end > start:
		elapsed_fraction = (today - start).days / (end - start).days
		schedule_pct = min(100.0, max(0.0, elapsed_fraction * 100))
		burn_gap = consumed_pct - schedule_pct
		if burn_gap > _BUDGET_BURN_AHEAD_THRESHOLD:
			lines.append(
				_quote(
					f"🟡 Budget burn ({consumed_pct:.0f}%) is running "
					f"{burn_gap:.0f} point(s) ahead of schedule burn "
					f"({schedule_pct:.0f}%)."
				),
			)

	return [
		_header_block("💰 Budget"),
		{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
	]


# One line per role, framed around the concrete consequence of the gap
# rather than a flat "field X is missing" -- matches the business-value
# framing used elsewhere in this bot (see pms-slack-automation-context).
_TEAM_ROLE_GAP_MESSAGES = {
	"Project Manager": (
		"🧑‍💼 *No Project Manager assigned* — nobody owns escalations or "
		"client communication on this project."
	),
	"Lead Engineer": (
		"🛠️ *No Lead Engineer assigned* — technical decisions and delivery "
		"risk have no clear owner."
	),
	"Team members": (
		"👥 *No team members beyond PM/Lead Engineer* — the project's roster "
		"doesn't reflect who's actually doing the work."
	),
}


def _format_team_section(
	project_id: str, project_detail: dict, shared_emails: list[str]
) -> list[dict]:
	"""Flag whichever of Project Manager / Lead Engineer / Team members is missing.

	Next PMS has no dedicated "team members" field -- its Members panel's
	team list is actually everyone the project is shared with (`DocShare`),
	minus the PM and Lead Engineer (who are shared too, but surfaced as
	their own roles rather than counted as generic members). Names the
	specific missing role(s), each framed around its concrete consequence
	rather than a flat "field is missing" list, and links straight to the
	project so fixing it is one click. Returns `[]` when PM, Lead Engineer,
	and at least one team member are all present.
	"""
	pm_email = project_detail.get(PROJECT_MANAGER_FIELD)
	em_email = project_detail.get(PROJECT_ENGINEERING_MANAGER_FIELD)
	excluded = {email for email in (pm_email, em_email) if email}
	team_members = [email for email in shared_emails if email not in excluded]

	missing = []
	if not pm_email:
		missing.append("Project Manager")
	if not em_email:
		missing.append("Lead Engineer")
	if not team_members:
		missing.append("Team members")

	if not missing:
		return []

	lines = [_quote(_TEAM_ROLE_GAP_MESSAGES[role]) for role in missing]
	return [
		_header_block("👥 Team"),
		{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
		_open_overview_button(project_id),
	]


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
			_quote("⚠️ No GitHub repository connected to this project in Next PMS.")
		)

	blocks.append(
		{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}
	)
	return blocks


def _todo_title(todo: dict) -> str:
	"""Pick a display title: `custom_title` if set, else derived from the description.

	`custom_title` is a NextPMS-specific field on `ToDo` and is expected to
	be populated, but falls back to the first line/sentence of the
	description (stripped of HTML) for any older record that predates it,
	rather than showing the full text truncated mid-sentence.
	"""
	custom_title = (todo.get("custom_title") or "").strip()
	if custom_title:
		return custom_title

	description = _strip_html(todo.get("description") or "")
	first_line = description.splitlines()[0].strip() if description else ""
	if not first_line:
		return "(no description)"
	sentence_end = first_line.find(". ")
	if sentence_end != -1:
		return first_line[:sentence_end].strip()
	return first_line


def _normalize_todo(todo: dict) -> dict:
	"""Normalize a standalone ToDo record into the Task-like shape formatters expect."""
	status = todo.get("status") or ""
	return {
		"name": todo["name"],
		"subject": _todo_title(todo),
		"status": TODO_STATUS_TO_TASK_STATUS.get(status, status),
		"is_milestone": 0,
		"exp_end_date": todo.get("date"),
	}


def _normalize_pti_milestone(pti: dict) -> dict:
	"""Normalize a Project Timeline Item (type=Milestone) into a Task-like shape.

	PTI uses different field names from Task: `title` instead of `subject`,
	`planned_end_date` instead of `exp_end_date`, and `is_complete` (0/1)
	instead of a `status` string. We derive a status string so the existing
	`_format_milestone_section` / `_categorize_milestones` logic works
	unchanged:
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
	shared_emails: list[str],
	github_repos: list[dict],
	github_issues: list[dict] | None,
	tips: dict,
	*,
	project_detail_unavailable: bool = False,
) -> tuple[str, list[dict]]:
	"""Build the /pms audit response as fallback text plus Block Kit blocks.

	`github_issues` is `None` when repos are connected but the GitHub API
	call itself failed (as opposed to `[]`, which means it succeeded and
	found nothing) -- these render as a distinct "couldn't fetch" section
	so a transient GitHub outage doesn't get mistaken for "no open issues"
	(genuinely zero issues still omits the section like everything else).
	`project_detail_unavailable` is the same idea for the project document
	itself: when its fetch failed, `project_detail` arrives as `{}` same as
	a real (impossible) empty document would, so without this flag every
	field derived from it -- missing fields, budget, team, RAG status,
	GitHub repo -- would misreport as "nothing set" instead of "couldn't
	check." Those sections are skipped entirely and replaced with one
	explicit warning instead. `tips` holds LLM-generated copy
	(`milestonesTip`/`todosTip`/`risksTip`/`githubTip`, any of which may be
	absent) -- empty dict falls back to hardcoded tips.

	Each section (Milestones/Todos/Risks/GitHub Issues) is entirely
	omitted -- no header, no placeholder text -- when it has no data at
	all, rather than shown as an empty section. Dividers are only inserted
	between sections that actually rendered something, so an omitted
	section never leaves a stray or doubled-up divider behind.
	"""
	project_id = project["name"]
	billing_type = project_detail.get(PROJECT_BILLING_TYPE_FIELD)
	is_retainer = billing_type == RETAINER_BILLING_TYPE
	is_active = project["status"] not in PROJECT_SUPPRESSED_STATUSES

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

	project_detail_warning: list[dict] = []
	if project_detail_unavailable:
		project_detail_warning = [
			{
				"type": "section",
				"text": {
					"type": "mrkdwn",
					"text": _quote(
						"⚠️ Could not load this project's details from Next PMS -- "
						"Missing Fields, Budget, and Team are skipped below (not "
						"actually empty, just unavailable right now). Re-run "
						"`/pms audit` to retry."
					),
				},
			},
		]

	sections = [
		list(_format_audit_header(project, project_detail, github_repos)),
		project_detail_warning,
		[] if project_detail_unavailable else _format_missing_fields_section(project),
		_format_milestone_section(
			milestones,
			_project_tab_url(project_id, "calendar"),
			is_retainer=is_retainer,
			llm_tip=tips.get("milestonesTip"),
		),
		_format_todo_section(
			"✅ Todos",
			todos,
			_project_tab_url(project_id, "to-do"),
			tips.get("todosTip"),
			milestones=milestones,
		),
		_format_risk_section(
			risks, _project_tab_url(project_id, "risks"), tips.get("risksTip")
		),
		[]
		if project_detail_unavailable
		else _format_budget_section(project_detail, is_retainer=is_retainer),
		[]
		if project_detail_unavailable or not is_active
		else _format_team_section(project_id, project_detail, shared_emails),
		github_section,
		[
			{
				"type": "context",
				"elements": [
					{
						"type": "mrkdwn",
						"text": (
							"_Pulled live from Next PMS. Re-run `/pms audit` "
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
	# Lazy import: app.llm.inngest imports app.slack.inngest (main.py pulls in
	# both), so importing this at module load time here would risk a
	# circular import depending on which package initializes first. By call
	# time all modules are already fully loaded.
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

	Milestones come exclusively from `Project Timeline Item` (type=Milestone)
	-- the doctype that actually powers ?tab=calendar in Next PMS. Todos come
	exclusively from the standalone `ToDo` doctype -- `Task` records are no
	longer queried for either milestones or todos.
	"""
	project_id = project["name"]
	(
		project_detail,
		pti_milestones,
		standalone_todos,
		risks,
		shared_emails,
	) = await asyncio.gather(
		frappe_service.get_project_by_id(project_id),
		frappe_service.get_milestones_by_project(project_id),
		frappe_service.get_todos_by_project(project_id),
		frappe_service.get_risks_by_project(project_id),
		frappe_service.get_project_shares(project_id),
	)
	# get_project_by_id returns None specifically on a failed/missing fetch
	# (never a real empty document) -- tracked separately so a fetch failure
	# doesn't get silently rendered as "every field is blank".
	project_detail_unavailable = project_detail is None
	project_detail = project_detail or {}

	milestones = [_normalize_pti_milestone(pti) for pti in pti_milestones]
	todos = [_normalize_todo(todo) for todo in standalone_todos]

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
		shared_emails,
		github_repos,
		github_issues,
		tips,
		project_detail_unavailable=project_detail_unavailable,
	)


async def _resolve_delivery_manager_override(
	frappe_service: FrappeService, email: str, project_filter: str
) -> dict | None:
	"""Let a Delivery Manager audit any project by exact ID, even if they're not its PM.

	Only called as a fallback when the requester isn't already the PM of a
	matching project (the common case) -- the role lookup costs an extra
	Frappe call, so it's skipped entirely unless needed. Requires an exact
	project ID match rather than the fuzzy name search PM-scoped lookups
	get, since there's no bounded "my projects" list to search within.
	"""
	roles = await frappe_service.get_user_roles(email)
	if DELIVERY_MANAGER_ROLE not in roles:
		return None
	return await frappe_service.get_project_by_id(project_filter)


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
