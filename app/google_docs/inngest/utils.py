"""Utility functions for Google Docs Inngest integration."""

import json
import logging
from datetime import date

from app.llm.models.summarization import ProjectMetadata, UserMetadata

logger = logging.getLogger(__name__)


def format_date(dt: date) -> str:
	"""Format date as 'December 25, 2025'.

	Args:
		dt: Date object to format.

	Returns:
		str: Formatted date string.

	Examples:
		>>> from datetime import date
		>>> format_date(date(2025, 12, 25))
		'December 25, 2025'

	"""
	return dt.strftime("%B %d, %Y")


def parse_llm_summary(json_str: str) -> dict:
	"""Parse LLM JSON string output.

	Args:
		json_str: JSON string from LLM summarization.

	Returns:
		dict: Parsed summary data.

	Raises:
		json.JSONDecodeError: If JSON is invalid.
		ValueError: If required fields are missing.

	"""
	try:
		data = json.loads(json_str)

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
		logger.error(f"Failed to parse LLM summary JSON: {e}")
		raise


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
		"from": format_date(project_metadata.start_date),
		"to": format_date(project_metadata.end_date),
		"name": user_metadata.user_name,
		"projectStatus": project_metadata.project_status.value,
		"summary": summary_data["summary"],
		"riskBlockerActionNeeded": summary_data["riskBlockerActionNeeded"],
		"completed": task_details["completed"],
		"inProgress": task_details["inProgress"],
		"inReview": task_details["inReview"],
	}


def generate_doc_name(project_name: str, end_date: date) -> str:
	"""Generate document name for Google Doc.

	Format: "{project_name} Report - {formatted_end_date}"

	Args:
		project_name: Name of the project.
		end_date: End date of the reporting period.

	Returns:
		str: Generated document name.

	Examples:
		>>> from datetime import date
		>>> generate_doc_name("AI Project", date(2025, 12, 25))
		'AI Project Report - December 25, 2025'

	"""
	# TODO(namankhare): https://github.com/rtCamp/rt-report-automation/pull/57
	# Update document name format.
	formatted_date = format_date(end_date)
	return f"{project_name} Report - {formatted_date}"
