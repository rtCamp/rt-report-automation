import datetime
import time

import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.llm.models.summarization import ProjectMetadata, SlackMetadata
from app.slack.service import SlackService


@inngest_client.create_function(
	fn_id="fetch_slack",
	trigger=inngest.TriggerEvent(event="rt-report-automation/fetch_slack"),
	retries=2,
)
async def fetch_slack(ctx: inngest.Context):
	try:
		event_data = ctx.event.data
		if not isinstance(event_data, dict):
			raise TypeError(
				f"Expected dict for event data, got {type(event_data).__name__}",
			)

		# Extract slack_metadata and project_metadata.
		slack_data = event_data.get("slack_metadata")
		project_metadata = event_data.get("project_metadata")

		# Validate slack_data is a dict.
		if not isinstance(slack_data, dict):
			raise TypeError(
				f"Expected dict, got {type(slack_data).__name__}",
			)

		# Validate project_metadata is a dict.
		if not isinstance(project_metadata, dict):
			raise TypeError(
				f"Expected dict, got {type(project_metadata).__name__}",
			)

		slack_metadata = SlackMetadata.model_validate(slack_data)
		project_metadata = ProjectMetadata.model_validate(project_metadata)

		def to_unix(dt):
			if isinstance(dt, datetime.date):
				return int(time.mktime(dt.timetuple()))
			return int(dt)

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
