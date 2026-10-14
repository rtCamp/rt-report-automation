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
