"""Inngest functions for Slack integration."""

import datetime

import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.utils import to_unix, validate
from app.llm.models.summarization import ProjectMetadata, SlackMetadata
from app.slack.constants import SLACK_API_RATE_LIMIT
from app.slack.service import SlackService


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

	The workflow name is determined by:
	- If slack_metadata.workflow_name is provided, it is used
	- Otherwise, it is generated as "{project_metadata.project_name} - Daily Tasks Tracker"

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- slack_metadata (dict): Slack configuration with channel_slug and optional workflow_name
			- project_metadata (dict): Project details with start_date, end_date, and project_name

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

		start_ts = to_unix(project_metadata.start_date)
		end_ts = to_unix(project_metadata.end_date)

		# Resolve workflow name: prefer override, else generate from project name
		workflow_name = (
			(slack_metadata.workflow_name or "").strip()
			or f"{project_metadata.project_name.strip()} - Daily Tasks Tracker"
		)

		slack_service = SlackService()

		return slack_service.get_standups(
			slack_metadata.channel_slug,
			start_ts,
			end_ts,
			workflow_name,
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
