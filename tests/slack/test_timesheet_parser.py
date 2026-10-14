"""Tests for the `/pms timesheets` command parser."""

import datetime as dt

import pytest

from app.slack.constants import TIMESHEET_CHECKS
from app.slack.services.timesheet_parser import (
	TimesheetQueryError,
	parse_timesheet_command,
	validate_date_range,
)

RANGE = "--from 2026-09-21 --to 2026-09-25"


def test_analyze_members_parses_into_query():
	query = parse_timesheet_command(f"analyze --members a,b {RANGE}")

	assert query.action == "analyze"
	assert query.target_type == "members"
	assert query.targets == ["a", "b"]
	assert query.from_date == dt.date(2026, 9, 21)
	assert query.to_date == dt.date(2026, 9, 25)
	assert query.days == 5
	assert query.checks == list(TIMESHEET_CHECKS)


def test_fetch_projects_gives_fetch_action_and_no_checks():
	query = parse_timesheet_command(f"fetch --projects PROJ-1 {RANGE}")

	assert query.action == "fetch"
	assert query.target_type == "projects"
	assert query.targets == ["PROJ-1"]
	assert query.checks == []


def test_action_is_case_insensitive():
	assert parse_timesheet_command(f"ANALYZE --members a {RANGE}").action == "analyze"


def test_flags_can_appear_in_any_order():
	query = parse_timesheet_command(
		"fetch --to 2026-09-25 --projects P --from 2026-09-21"
	)

	assert query.targets == ["P"]
	assert query.days == 5


def test_targets_are_trimmed_and_deduplicated():
	query = parse_timesheet_command(f"analyze --members a, b ,a {RANGE}")

	assert query.targets == ["a", "b"]


def test_selected_checks_are_kept_in_order():
	query = parse_timesheet_command(
		f"analyze --projects P {RANGE} --checks gaps,DUPLICATES,gaps"
	)

	assert query.checks == ["gaps", "duplicates"]


def test_single_day_range_is_accepted():
	query = parse_timesheet_command(
		"analyze --members a --from 2026-09-21 --to 2026-09-21"
	)

	assert query.days == 1


def test_exactly_90_days_is_accepted():
	query = parse_timesheet_command(
		"analyze --members a --from 2026-07-01 --to 2026-09-28"
	)

	assert query.days == 90


def test_91_days_is_rejected_with_limit_and_suggested_window():
	with pytest.raises(TimesheetQueryError) as exc:
		parse_timesheet_command("analyze --members a --from 2026-06-30 --to 2026-09-28")

	message = str(exc.value)
	assert "91 days" in message
	assert "limit is 90 days" in message
	assert "`--from 2026-07-01 --to 2026-09-28`" in message


@pytest.mark.parametrize(
	("text", "expected"),
	[
		(f"analyze --members a --projects P {RANGE}", "not both"),
		(f"analyze {RANGE}", "Specify `--members` or `--projects`"),
		(f"analyze --members , , {RANGE}", "needs at least one ID"),
		("analyze --members a --to 2026-09-25", "Missing `--from`"),
		("analyze --members a --from 2026-09-21", "Missing `--to`"),
		("analyze --members a --from 2026-02-30 --to 2026-03-02", "not a valid date"),
		("analyze --members a --from 20260921 --to 2026-09-25", "must be a date like"),
		("analyze --members a --from 2026-09-25 --to 2026-09-21", "is after"),
		(f"analyze --members a --members b {RANGE}", "more than once"),
		(f"analyze --members {RANGE}", "`--members` needs a value"),
		(f"fetch --projects P {RANGE} --checks gaps", "only applies to `analyze`"),
		(f"analyze --projects P {RANGE} --checks", "`--checks` needs a value"),
	],
)
def test_invalid_commands_are_rejected(text, expected):
	with pytest.raises(TimesheetQueryError, match=expected) as exc:
		parse_timesheet_command(text)

	assert not exc.value.show_usage


def test_unknown_check_is_named():
	with pytest.raises(TimesheetQueryError) as exc:
		parse_timesheet_command(f"analyze --projects P {RANGE} --checks duplicates,foo")

	assert "`foo`" in str(exc.value)
	assert "`duplicates`" not in str(exc.value).split("Valid checks")[0]


@pytest.mark.parametrize(
	"text",
	[
		"",
		f"review --members a {RANGE}",
		f"analyze --members a {RANGE} --verbose",
		f"analyze stray --members a {RANGE}",
	],
)
def test_malformed_commands_ask_for_usage(text):
	with pytest.raises(TimesheetQueryError) as exc:
		parse_timesheet_command(text)

	assert exc.value.show_usage


def test_validate_date_range_accepts_valid_range():
	validate_date_range(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
