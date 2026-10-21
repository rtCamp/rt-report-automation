"""Fetch the time logs a `/pms timesheets` request covers, and total them.

Long ranges are split into windows fetched concurrently. A window that fails,
or comes back short of the server's own count, is reported as a limitation
rather than failing the whole request.
"""

import asyncio
import datetime as dt
import logging

import html2text

from app.frappe.constants import TIMESHEET_DRAFT_DOCSTATUS
from app.frappe.service import FrappeService
from app.slack.models.timesheets import (
	FetchLimitation,
	HoursTotal,
	ResolvedTargets,
	TimesheetEntry,
	TimesheetFetchResult,
	TimesheetQuery,
	TimesheetTotals,
)

logger = logging.getLogger(__name__)

BATCH_DAYS = 30
UNASSIGNED_PROJECT = "(no project)"
UNASSIGNED_EMPLOYEE = "(no employee)"


def split_into_batches(
	from_date: dt.date, to_date: dt.date, days: int = BATCH_DAYS
) -> list[tuple[dt.date, dt.date]]:
	"""Split an inclusive date range into consecutive, non-overlapping windows."""
	batches = []
	start = from_date
	while start <= to_date:
		end = min(start + dt.timedelta(days=days - 1), to_date)
		batches.append((start, end))
		start = end + dt.timedelta(days=1)
	return batches


def _to_text(html: str | None) -> str:
	if not html:
		return ""
	converter = html2text.HTML2Text()
	converter.ignore_links = True
	converter.ignore_images = True
	converter.body_width = 0  # No line wrapping
	return converter.handle(html).strip()


def _to_entry(row: dict) -> TimesheetEntry:
	from_time = row["from_time"]
	if isinstance(from_time, str):
		from_time = dt.datetime.fromisoformat(from_time)
	return TimesheetEntry(
		detail_id=row["detail_id"],
		timesheet=row["timesheet"],
		employee=row.get("employee"),
		project=row.get("project"),
		task=row.get("task"),
		date=from_time.date(),
		hours=float(row.get("hours") or 0),
		description=_to_text(row.get("description")),
		is_draft=row.get("docstatus") == TIMESHEET_DRAFT_DOCSTATUS,
	)


def _add(total: HoursTotal, entry: TimesheetEntry) -> None:
	if entry.is_draft:
		total.draft_hours += entry.hours
	else:
		total.hours += entry.hours


def compute_totals(entries: list[TimesheetEntry]) -> TimesheetTotals:
	"""Total hours overall and per member, project and day.

	Draft hours are counted separately from submitted ones.
	"""
	totals = TimesheetTotals(overall=HoursTotal())
	for entry in entries:
		project = entry.project or UNASSIGNED_PROJECT
		_add(totals.overall, entry)
		member = entry.employee or UNASSIGNED_EMPLOYEE
		_add(totals.per_member.setdefault(member, HoursTotal()), entry)
		_add(totals.per_project.setdefault(project, HoursTotal()), entry)
		_add(totals.per_day.setdefault(entry.date, HoursTotal()), entry)
	return totals


def _filters(
	query: TimesheetQuery, targets: ResolvedTargets
) -> tuple[list[str] | None, list[str] | None]:
	"""Work out the employee and project filters for a request."""
	employees = None
	project_ids = None
	if query.target_type == "members":
		employees = [e.employee_id for e in targets.employees]
	else:
		project_ids = targets.project_ids
	# A restricted requester only ever sees the projects in their scope.
	if not targets.scope.all_projects:
		scoped = targets.scope.project_ids
		project_ids = (
			scoped if project_ids is None else [p for p in project_ids if p in scoped]
		)
	return employees, project_ids


async def _fetch_batch(
	frappe: FrappeService,
	window: tuple[dt.date, dt.date],
	employees: list[str] | None,
	project_ids: list[str] | None,
) -> list[TimesheetEntry]:
	"""Fetch and convert one window, raising if it is incomplete or malformed.

	Converting here, rather than after merging, means one bad row costs only
	its own window.
	"""
	start, end = window
	rows, expected = await asyncio.gather(
		frappe.get_timesheet_entries(
			start, end, employees=employees, project_ids=project_ids
		),
		frappe.get_timesheet_entry_count(
			start, end, employees=employees, project_ids=project_ids
		),
	)
	entries = {row["detail_id"]: _to_entry(row) for row in rows}
	# Distinct ids, not raw rows: rows can repeat when offset pages overlap.
	if len(entries) < expected:
		msg = f"retrieved {len(entries)} of {expected} entries"
		raise RuntimeError(msg)
	return list(entries.values())


async def fetch_timesheets(
	query: TimesheetQuery,
	targets: ResolvedTargets,
	frappe: FrappeService,
) -> TimesheetFetchResult:
	"""Fetch every entry the request covers, in batches, and total them.

	Windows that fail or come back incomplete are skipped and listed in
	`limitations`; entries from the other windows are still returned.
	"""
	employees, project_ids = _filters(query, targets)
	windows = split_into_batches(query.from_date, query.to_date)
	outcomes = await asyncio.gather(
		*(_fetch_batch(frappe, w, employees, project_ids) for w in windows),
		return_exceptions=True,
	)

	entries: dict[str, TimesheetEntry] = {}
	limitations = []
	for (start, end), outcome in zip(windows, outcomes, strict=True):
		if isinstance(outcome, BaseException):
			logger.warning(
				"Timesheet batch %s to %s incomplete: %s", start, end, outcome
			)
			limitations.append(
				FetchLimitation(from_date=start, to_date=end, reason=str(outcome))
			)
			continue
		for entry in outcome:
			# Dedupe on the detail row id as a safety net against overlap.
			entries.setdefault(entry.detail_id, entry)

	ordered = sorted(entries.values(), key=lambda e: (e.date, e.detail_id))
	return TimesheetFetchResult(
		entries=ordered,
		totals=compute_totals(ordered),
		limitations=limitations,
	)
