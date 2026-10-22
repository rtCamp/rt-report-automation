"""Parser for the `/pms timesheets` slash command.

Pure text-in, query-out: no Slack, Frappe or network access, so the same
validation can back the typed command and the `/pms timesheets` modal.
"""

import datetime as dt
import re
from typing import cast, get_args

from app.slack.constants import TIMESHEET_CHECKS, TIMESHEET_MAX_RANGE_DAYS
from app.slack.models.timesheets import TimesheetAction, TimesheetQuery

_FLAGS = frozenset({"members", "projects", "from", "to", "checks"})

# `fromisoformat` alone also accepts forms like `20260921` and `2026-W38-1`;
# pin the documented `YYYY-MM-DD` shape before handing it over.
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class TimesheetQueryError(ValueError):
	"""A `/pms timesheets` command that can't be turned into a query.

	The message is written for the Slack user and shown as-is.
	"""

	def __init__(self, message: str, *, show_usage: bool = False):
		"""Store the user-facing message and whether to append usage text."""
		super().__init__(message)
		self.show_usage = show_usage


def parse_timesheet_command(text: str) -> TimesheetQuery:
	"""Parse the arguments after `/pms timesheets` into a validated query.

	Args:
		text (str): Everything after the `timesheets` subcommand, e.g.
			`analyze --members EMP-001,EMP-002 --from 2026-09-21 --to 2026-09-25`.

	Returns:
		TimesheetQuery: The validated request.

	Raises:
		TimesheetQueryError: If the command is malformed or fails validation.

	"""
	tokens = text.split()
	if not tokens:
		raise TimesheetQueryError("Missing action.", show_usage=True)

	if tokens[0].lower() not in get_args(TimesheetAction):
		raise TimesheetQueryError(
			f"Unknown action `{tokens[0]}`. Use `analyze` or `fetch`.",
			show_usage=True,
		)
	action = cast("TimesheetAction", tokens[0].lower())

	flags = _collect_flags(tokens[1:])

	if "members" in flags and "projects" in flags:
		raise TimesheetQueryError("Use either `--members` or `--projects`, not both.")
	if "members" not in flags and "projects" not in flags:
		raise TimesheetQueryError("Specify `--members` or `--projects`.")
	target_type = "members" if "members" in flags else "projects"

	targets = _split_list(flags[target_type])
	if not targets:
		raise TimesheetQueryError(f"`--{target_type}` needs at least one ID.")

	from_date = _parse_date(flags, "from")
	to_date = _parse_date(flags, "to")
	validate_date_range(from_date, to_date)

	return TimesheetQuery(
		action=action,
		target_type=target_type,
		targets=targets,
		from_date=from_date,
		to_date=to_date,
		checks=_parse_checks(action, flags.get("checks")),
	)


def validate_date_range(from_date: dt.date, to_date: dt.date) -> None:
	"""Reject an inverted range or one longer than the inclusive limit.

	Raises:
		TimesheetQueryError: If `from_date` is after `to_date`, or the range
			spans more than `TIMESHEET_MAX_RANGE_DAYS` days.

	"""
	if from_date > to_date:
		raise TimesheetQueryError(
			f"`--from` ({from_date}) is after `--to` ({to_date}).",
		)

	days = (to_date - from_date).days + 1
	if days > TIMESHEET_MAX_RANGE_DAYS:
		suggested_from = to_date - dt.timedelta(days=TIMESHEET_MAX_RANGE_DAYS - 1)
		raise TimesheetQueryError(
			f"That range is {days} days; the limit is "
			f"{TIMESHEET_MAX_RANGE_DAYS} days (inclusive). Try "
			f"`--from {suggested_from} --to {to_date}` for the latest "
			f"{TIMESHEET_MAX_RANGE_DAYS} days ending on `--to`.",
		)


def _collect_flags(tokens: list[str]) -> dict[str, str]:
	"""Group tokens under the flag before them.

	A flag's value is every token up to the next flag, re-joined with spaces,
	so a list typed with spaces (`--members a, b ,a`) still reads as one value.
	"""
	values: dict[str, list[str]] = {}
	current: str | None = None

	for token in tokens:
		if token.startswith("--"):
			name = token[2:].lower()
			if name not in _FLAGS:
				raise TimesheetQueryError(f"Unknown flag `{token}`.", show_usage=True)
			if name in values:
				raise TimesheetQueryError(f"`{token}` is given more than once.")
			values[name] = []
			current = name
		elif current is None:
			raise TimesheetQueryError(f"Unexpected `{token}`.", show_usage=True)
		else:
			values[current].append(token)

	flags = {name: " ".join(parts) for name, parts in values.items()}
	for name, value in flags.items():
		if not value:
			raise TimesheetQueryError(f"`--{name}` needs a value.")
	return flags


def _split_list(value: str) -> list[str]:
	"""Split a comma-separated value, trimming and de-duplicating in order."""
	items = (item.strip() for item in value.split(","))
	return list(dict.fromkeys(item for item in items if item))


def _parse_date(flags: dict[str, str], name: str) -> dt.date:
	"""Read a required `YYYY-MM-DD` flag value as a date."""
	value = flags.get(name)
	if value is None:
		raise TimesheetQueryError(f"Missing `--{name}` (YYYY-MM-DD).")

	if not _DATE_PATTERN.fullmatch(value):
		raise TimesheetQueryError(
			f"`--{name}` must be a date like 2026-09-21, got `{value}`.",
		)
	try:
		return dt.date.fromisoformat(value)
	except ValueError:
		raise TimesheetQueryError(
			f"`--{name}` is not a valid date: `{value}`.",
		) from None


def _parse_checks(action: TimesheetAction, value: str | None) -> list[str]:
	"""Resolve `--checks` into a list of check names.

	`fetch` runs no checks, so passing `--checks` with it is rejected rather
	than silently ignored. For `analyze`, omitting the flag selects every check.
	"""
	if action == "fetch":
		if value is not None:
			raise TimesheetQueryError(
				"`--checks` only applies to `analyze`; `fetch` runs no checks.",
			)
		return []

	if value is None:
		return list(TIMESHEET_CHECKS)

	checks = _split_list(value.lower())
	if not checks:
		raise TimesheetQueryError("`--checks` needs at least one check.")

	unknown = [check for check in checks if check not in TIMESHEET_CHECKS]
	if unknown:
		valid = ", ".join(f"`{check}`" for check in TIMESHEET_CHECKS)
		raise TimesheetQueryError(
			f"Unknown check{'s' if len(unknown) > 1 else ''}: "
			f"{', '.join(f'`{check}`' for check in unknown)}. Valid checks: {valid}.",
		)
	return checks
