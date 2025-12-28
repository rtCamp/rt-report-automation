"""Utility functions for Google Docs Inngest integration."""

import json
import logging
from datetime import date

from app.core.utils import log_and_raise
from app.llm.models.summarization import ProjectMetadata, UserMetadata

logger = logging.getLogger(__name__)


def to_ordinal(n: int) -> str:
	"""Convert number to ordinal string (1st, 2nd, 3rd, etc.).

	Args:
		n: Integer to convert.

	Returns:
		str: Ordinal string representation.

	Examples:
		>>> to_ordinal(1)
		'1st'
		>>> to_ordinal(2)
		'2nd'
		>>> to_ordinal(3)
		'3rd'
		>>> to_ordinal(21)
		'21st'
		>>> to_ordinal(22)
		'22nd'

	"""
	if 10 <= n % 100 <= 20:
		suffix = "th"
	else:
		suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
	return f"{n}{suffix}"


def format_date_to_ordinal(date_obj: date) -> str:
	"""Format date as '1st Dec 2025'.

	Args:
		date_obj: Date object to format.

	Returns:
		str: Formatted date string with ordinal day.

	Examples:
		>>> from datetime import date
		>>> format_date_to_ordinal(date(2025, 12, 1))
		'1st Dec 2025'
		>>> format_date_to_ordinal(date(2025, 12, 25))
		'25th Dec 2025'

	"""
	ordinal_day = to_ordinal(date_obj.day)
	return f"{ordinal_day} {date_obj.strftime('%b %Y')}"


def parse_llm_summary(summary_data: str | dict) -> dict:
	"""Parse and normalize LLM summary output.

	Handles both JSON string and dict inputs. Inngest may auto-deserialize
	JSON strings between steps, so we accept both formats.

	Args:
		summary_data: JSON string or dict from LLM summarization.
			- str: '{"summary": "...", "risk_blocker_action_needed": "...", ...}'
			- dict: {"summary": "...", "risk_blocker_action_needed": "...", ...}

	Returns:
		dict: Normalized summary data with camelCase fields.
			Example: {"summary": "...", "riskBlockerActionNeeded": "...", ...}

	Raises:
		json.JSONDecodeError: If JSON string is invalid.
		ValueError: If required fields are missing.

	"""
	try:
		# Convert to dict if needed
		if isinstance(summary_data, str):
			data = json.loads(summary_data)
		else:
			data = summary_data

		# Validate required fields
		required_fields = ["summary", "riskBlockerActionNeeded", "taskDetails"]
		missing_fields = [field for field in required_fields if field not in data]

		if missing_fields:
			raise ValueError(f"Missing required fields in summary: {missing_fields}")

		task_details = data.get("taskDetails", {})
		required_task_fields = ["completed", "inProgress", "inReview"]
		missing_task_fields = [
			field for field in required_task_fields if field not in task_details
		]

		if missing_task_fields:
			raise ValueError(
				f"Missing required taskDetails fields: {missing_task_fields}",
			)

		return data

	except json.JSONDecodeError as e:
		log_and_raise(
			logger,
			"Failed to parse LLM summary JSON",
			json.JSONDecodeError,
			cause=e,
		)
	except (KeyError, ValueError) as e:
		log_and_raise(
			logger,
			f"Invalid LLM summary data: {e}",
			type(e),
			cause=e,
		)


def build_replacements_dict(
	summary_data: dict,
	project_metadata: ProjectMetadata,
	user_metadata: UserMetadata,
) -> dict[str, str | list[str]]:
	"""Transform LLM output to Google Docs replacements format.

	Args:
		summary_data: Parsed LLM summary containing summary, riskBlockerActionNeeded,
			and taskDetails.
		project_metadata: Project metadata with name, dates, and status.
		user_metadata: User metadata with user name.

	Returns:
		dict: Replacements dictionary formatted for Google Docs template.

	Raises:
		KeyError: If required fields are missing from input data.

	Examples:
		>>> summary_data = {
		...     "summary": "Project is on track",
		...     "riskBlockerActionNeeded": "No blockers",
		...     "taskDetails": {
		...         "completed": "Feature A",
		...         "inProgress": "Feature B",
		...         "inReview": "Feature C"
		...     }
		... }
		>>> # project_metadata and user_metadata would be Pydantic models
		>>> # build_replacements_dict(summary_data, project_metadata, user_metadata)

	"""
	task_details = summary_data["taskDetails"]

	return {
		"projectName": project_metadata.project_name,
		"from": format_date_to_ordinal(project_metadata.start_date),
		"to": format_date_to_ordinal(project_metadata.end_date),
		"name": user_metadata.user_name,
		"projectStatus": project_metadata.project_status.value,
		"summary": summary_data["summary"],
		"riskBlockerActionNeeded": summary_data["riskBlockerActionNeeded"],
		"completed": task_details["completed"],
		"inProgress": task_details["inProgress"],
		"inReview": task_details["inReview"],
	}


def generate_doc_name(project_name: str, start_date: date, end_date: date) -> str:
	"""Generate document name for Google Doc.

	Format: "{project_name} - {start_date} - {end_date}"

	Args:
		project_name: Name of the project.
		start_date: Start date of the reporting period.
		end_date: End date of the reporting period.

	Returns:
		str: Generated document name.

	Examples:
		>>> from datetime import date
		>>> generate_doc_name("AI Project", date(2025, 12, 1), date(2025, 12, 25))
		'AI Project - 1st Dec 2025 - 25th Dec 2025'

	"""
	formatted_start = format_date_to_ordinal(start_date)
	formatted_end = format_date_to_ordinal(end_date)
	return f"{project_name} - {formatted_start} - {formatted_end}"
