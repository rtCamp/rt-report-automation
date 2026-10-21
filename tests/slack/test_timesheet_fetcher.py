"""Tests for batched timesheet fetching and totals."""

import datetime as dt
import itertools
import json
from typing import Literal

import httpx
import pytest

from app.frappe.constants import TIMESHEET_PAGE_SIZE
from app.frappe.service import FrappeService
from app.slack.models.timesheets import (
	AccessScope,
	ResolvedEmployee,
	ResolvedTargets,
	TimesheetEntry,
	TimesheetQuery,
)
from app.slack.services.timesheet_fetcher import (
	compute_totals,
	fetch_timesheets,
	split_into_batches,
)

D = dt.date


def make_query(
	from_date, to_date, target_type: Literal["members", "projects"] = "members"
):
	return TimesheetQuery(
		action="fetch",
		target_type=target_type,
		targets=["x"],
		from_date=from_date,
		to_date=to_date,
		checks=[],
	)


def members(scope=None):
	return ResolvedTargets(
		scope=scope or AccessScope(all_projects=True),
		employees=[
			ResolvedEmployee(employee_id="EMP-001", employee_name="A", email=None)
		],
	)


def row(n, day, hours=1.0, docstatus=1, project="PROJ-1", description="<p>hi</p>"):
	return {
		"detail_id": f"d{n}",
		"timesheet": "TS-1",
		"employee": "EMP-001",
		"docstatus": docstatus,
		"project": project,
		"task": None,
		"from_time": f"{day.isoformat()} 09:00:00",
		"hours": hours,
		"description": description,
	}


def server(mock_http, all_rows, *, fail_from=None, count_offset=0):
	"""Serve `all_rows` honouring the requested window, paging and docstatus."""

	def handler(request: httpx.Request) -> httpx.Response:
		params = request.url.params
		filters = json.loads(params["filters"])
		window = next(f for f in filters if f[1] == "from_time")[3]
		start, end = (dt.date.fromisoformat(d) for d in window)
		if fail_from and start == fail_from:
			return httpx.Response(500)
		wanted = [
			r
			for r in all_rows
			if start <= dt.datetime.fromisoformat(r["from_time"]).date() <= end
			and r["docstatus"] in (0, 1)
		]
		for f in filters:
			if f[1] == "project":
				wanted = [r for r in wanted if r["project"] in f[3]]
		if request.url.path.endswith("get_count"):
			return httpx.Response(200, json={"message": len(wanted) + count_offset})
		first = int(params["limit_start"])
		size = int(params["limit_page_length"])
		return httpx.Response(200, json={"data": wanted[first : first + size]})

	return mock_http(handler)


def test_split_90_days_has_no_gaps_or_overlaps():
	batches = split_into_batches(D(2026, 7, 1), D(2026, 9, 28))
	assert len(batches) == 3
	assert batches[0][0] == D(2026, 7, 1)
	assert batches[-1][1] == D(2026, 9, 28)
	for (_, end), (start, _) in itertools.pairwise(batches):
		assert start == end + dt.timedelta(days=1)


def test_split_single_day():
	assert split_into_batches(D(2026, 9, 1), D(2026, 9, 1)) == [
		(D(2026, 9, 1), D(2026, 9, 1))
	]


@pytest.mark.asyncio
async def test_both_date_edges_included(mock_http):
	rows = [row(1, D(2026, 9, 1)), row(2, D(2026, 9, 5)), row(3, D(2026, 9, 6))]
	server(mock_http, rows)
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 5)), members(), FrappeService()
	)
	assert [e.detail_id for e in result.entries] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_batched_90_days_matches_single_fetch(mock_http):
	days = [D(2026, 7, 1) + dt.timedelta(days=i) for i in range(90)]
	rows = [row(i, d) for i, d in enumerate(days)]
	server(mock_http, rows)
	result = await fetch_timesheets(
		make_query(days[0], days[-1]), members(), FrappeService()
	)
	assert [e.detail_id for e in result.entries] == [r["detail_id"] for r in rows]
	assert result.limitations == []


@pytest.mark.asyncio
async def test_pages_are_merged(mock_http):
	n = TIMESHEET_PAGE_SIZE + 5
	rows = [row(i, D(2026, 9, 1)) for i in range(n)]
	requests = server(mock_http, rows)
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	assert len(result.entries) == n
	assert len([r for r in requests if "get_count" not in r.url.path]) == 2


@pytest.mark.asyncio
async def test_draft_labelled_and_cancelled_excluded(mock_http):
	rows = [row(1, D(2026, 9, 1), docstatus=0), row(2, D(2026, 9, 1), docstatus=2)]
	server(mock_http, rows)
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	assert [(e.detail_id, e.is_draft) for e in result.entries] == [("d1", True)]


@pytest.mark.asyncio
async def test_pm_scope_adds_project_filter(mock_http):
	rows = [
		row(1, D(2026, 9, 1), project="PROJ-1"),
		row(2, D(2026, 9, 1), project="PROJ-9"),
	]
	requests = server(mock_http, rows)
	scope = AccessScope(all_projects=False, project_ids=["PROJ-1"])
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(scope), FrappeService()
	)
	assert [e.project for e in result.entries] == ["PROJ-1"]
	filters = json.loads(requests[0].url.params["filters"])
	assert ["Timesheet Detail", "project", "in", ["PROJ-1"]] in filters


@pytest.mark.asyncio
async def test_all_scope_has_no_project_filter(mock_http):
	requests = server(mock_http, [])
	await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	filters = json.loads(requests[0].url.params["filters"])
	assert not any(f[1] == "project" for f in filters)


@pytest.mark.asyncio
async def test_fewer_than_server_count_is_incomplete(mock_http):
	server(mock_http, [row(1, D(2026, 9, 1))], count_offset=2)
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	assert len(result.limitations) == 1
	assert result.limitations[0].from_date == D(2026, 9, 1)
	assert result.entries == []


@pytest.mark.asyncio
async def test_failed_batch_keeps_others(mock_http):
	rows = [row(1, D(2026, 7, 1)), row(2, D(2026, 8, 15))]
	server(mock_http, rows, fail_from=D(2026, 7, 1))
	result = await fetch_timesheets(
		make_query(D(2026, 7, 1), D(2026, 9, 28)), members(), FrappeService()
	)
	assert [e.detail_id for e in result.entries] == ["d2"]
	assert [(lim.from_date, lim.to_date) for lim in result.limitations] == [
		(D(2026, 7, 1), D(2026, 7, 30))
	]


@pytest.mark.asyncio
async def test_html_description_becomes_text(mock_http):
	server(mock_http, [row(1, D(2026, 9, 1), description="<p>fixed <b>bug</b></p>")])
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	assert result.entries[0].description == "fixed **bug**"


def entry(n, day, hours, *, employee="E1", project="P1", draft=False):
	return TimesheetEntry(
		detail_id=f"d{n}",
		timesheet="TS",
		employee=employee,
		project=project,
		task=None,
		date=day,
		hours=hours,
		description="",
		is_draft=draft,
	)


def test_totals_group_and_split_drafts():
	totals = compute_totals(
		[
			entry(1, D(2026, 9, 1), 2),
			entry(2, D(2026, 9, 1), 3, employee="E2", project="P2", draft=True),
			entry(3, D(2026, 9, 2), 1),
		]
	)
	assert (totals.overall.hours, totals.overall.draft_hours) == (3, 3)
	assert totals.per_member["E1"].hours == 3
	assert totals.per_member["E2"].draft_hours == 3
	assert totals.per_project["P2"].draft_hours == 3
	assert totals.per_day[D(2026, 9, 1)].hours == 2
	assert totals.per_day[D(2026, 9, 1)].draft_hours == 3


@pytest.mark.asyncio
async def test_empty_result_has_zero_totals(mock_http):
	server(mock_http, [])
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	assert result.entries == []
	assert result.limitations == []
	assert result.totals.overall.hours == 0


@pytest.mark.asyncio
async def test_duplicate_rows_do_not_hide_a_short_window(mock_http):
	# Overlapping pages repeat a row: 2 raw rows, but only 1 distinct id,
	# against a server count of 2.
	rows = [row(1, D(2026, 9, 1)), row(1, D(2026, 9, 1))]
	server(mock_http, rows, count_offset=0)
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1)), members(), FrappeService()
	)
	assert result.entries == []
	assert len(result.limitations) == 1


@pytest.mark.asyncio
async def test_project_target_with_unassigned_employee(mock_http):
	unassigned = {**row(1, D(2026, 9, 1), hours=2), "employee": None}
	server(mock_http, [unassigned, row(2, D(2026, 9, 1))])
	targets = ResolvedTargets(
		scope=AccessScope(all_projects=True), project_ids=["PROJ-1"]
	)
	result = await fetch_timesheets(
		make_query(D(2026, 9, 1), D(2026, 9, 1), "projects"), targets, FrappeService()
	)
	assert len(result.entries) == 2
	assert result.limitations == []
	assert result.totals.per_member["(no employee)"].hours == 2


@pytest.mark.asyncio
async def test_malformed_row_limits_only_its_window(mock_http):
	bad = {**row(1, D(2026, 7, 1)), "hours": "not-a-number"}
	server(mock_http, [bad, row(2, D(2026, 8, 15))])
	result = await fetch_timesheets(
		make_query(D(2026, 7, 1), D(2026, 9, 28)), members(), FrappeService()
	)
	assert [e.detail_id for e in result.entries] == ["d2"]
	assert [lim.from_date for lim in result.limitations] == [D(2026, 7, 1)]
