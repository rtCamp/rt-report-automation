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
	"""Inngest function to fetch and parse standup messages from Slack.

	Retrieves standup messages from a specified Slack channel within a given
	date range and returns parsed standup data organized by timestamp.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- slack_metadata (dict): Slack configuration with channel_slug
			- project_metadata (dict): Project details with start_date and end_date

	Returns:
		dict[str, list[dict]]: Dictionary where keys are ISO timestamp strings
			and values are lists of parsed standup dictionaries. Each standup
			contains 'yesterday', 'today', 'blocker', and 'demo' sections.

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
		project_metadata = event_data.get("project_metadata")

		validate(slack_data, dict)
		validate(project_metadata, dict)

		slack_metadata = SlackMetadata.model_validate(slack_data)
		project_metadata = ProjectMetadata.model_validate(project_metadata)

		start_ts = to_unix(project_metadata.start_date)
		end_ts = to_unix(project_metadata.end_date)

		slack_service = SlackService()

		return slack_service.get_standups(
			slack_metadata.channel_slug,
			start_ts,
			end_ts,
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
