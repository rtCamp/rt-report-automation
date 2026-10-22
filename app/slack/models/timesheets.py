"""Data model for a parsed `/pms timesheets` request."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict

TimesheetAction = Literal["analyze", "fetch"]


class TimesheetQuery(BaseModel):
	"""A validated timesheet review request.

	Built by the `/pms timesheets` command parser (and, later, the modal), so
	both entry points hand downstream steps the same shape. Pydantic rather
	than a dataclass so it can travel as an Inngest event via `model_dump`.
	"""

	model_config = ConfigDict(frozen=True)

	action: TimesheetAction
	target_type: Literal["members", "projects"]
	targets: list[str]
	from_date: dt.date
	to_date: dt.date
	# Empty for `fetch`, which runs no checks.
	checks: list[str]

	@property
	def days(self) -> int:
		"""Length of the requested range in days, inclusive of both ends."""
		return (self.to_date - self.from_date).days + 1


class ResolvedEmployee(BaseModel):
	"""An Employee a member target resolved to."""

	model_config = ConfigDict(frozen=True)

	employee_id: str
	employee_name: str
	# Frappe User `name` (email); None for an Employee with no linked user.
	email: str | None


class AccessScope(BaseModel):
	"""Which projects' timesheet entries the requester may see.

	Ticket 3 applies this as a fetch filter: `all_projects` means no project
	filter, otherwise restrict to `project_ids`.
	"""

	model_config = ConfigDict(frozen=True)

	all_projects: bool
	project_ids: list[str] = []


class ResolvedTargets(BaseModel):
	"""Outcome of resolving a `TimesheetQuery`'s targets and checking access."""

	model_config = ConfigDict(frozen=True)

	scope: AccessScope
	# Exactly one of these is populated, matching the query's `target_type`.
	employees: list[ResolvedEmployee] = []
	project_ids: list[str] = []
	# Reported back to the requester; the rest of the request continues.
	not_found: list[str] = []
	denied: list[str] = []


class TimesheetEntry(BaseModel):
	"""One time log (a `Timesheet Detail` row) with its parent's context."""

	model_config = ConfigDict(frozen=True)

	detail_id: str
	timesheet: str
	# None when the parent Timesheet has no employee.
	employee: str | None
	project: str | None
	task: str | None
	date: dt.date
	hours: float
	# Plain text; Frappe stores HTML.
	description: str
	# The parent Timesheet isn't submitted yet.
	is_draft: bool


class FetchLimitation(BaseModel):
	"""A date window whose entries could not be fully retrieved."""

	model_config = ConfigDict(frozen=True)

	from_date: dt.date
	to_date: dt.date
	reason: str


class HoursTotal(BaseModel):
	"""Hours for one grouping, with draft hours kept apart from submitted."""

	hours: float = 0.0
	draft_hours: float = 0.0


class TimesheetTotals(BaseModel):
	"""Hours rolled up overall and per member, project and day."""

	overall: HoursTotal = HoursTotal()
	per_member: dict[str, HoursTotal] = {}
	per_project: dict[str, HoursTotal] = {}
	per_day: dict[dt.date, HoursTotal] = {}


class TimesheetFetchResult(BaseModel):
	"""Entries for a query, their totals, and any window that is incomplete."""

	entries: list[TimesheetEntry] = []
	totals: TimesheetTotals = TimesheetTotals()
	limitations: list[FetchLimitation] = []
