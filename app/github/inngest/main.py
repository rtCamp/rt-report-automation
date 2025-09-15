import datetime

import inngest
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.utils import to_unix, validate
from app.github.service import GitHubDataService
from app.github.utils.constants import (
	GITHUB_API_RATE_LIMIT,
	GITHUB_SERVICE_FAILURE_MAX_RETRY_LIMIT,
)
from app.llm.models.summarization import GitHubMetadata, ProjectMetadata


@inngest_client.create_function(
	fn_id="fetch_github_issues",
	trigger=inngest.TriggerEvent(event="rt-report-automation/fetch_github_issues"),
	retries=GITHUB_SERVICE_FAILURE_MAX_RETRY_LIMIT,
	throttle=inngest.Throttle(
		limit=GITHUB_API_RATE_LIMIT,
		period=datetime.timedelta(minutes=1),
	),
)
async def fetch_github_issues(ctx: inngest.Context):
	try:
		event_data = ctx.event.data
		validate(event_data, dict)

		github_data = event_data.get("github_metadata")
		project_metadata = event_data.get("project_metadata")

		validate(github_data, dict)
		validate(project_metadata, dict)

		github_metadata = GitHubMetadata.model_validate(github_data)
		project_metadata = ProjectMetadata.model_validate(project_metadata)

		# Daterange for the GitHub issues
		start_ts = to_unix(project_metadata.start_date)
		end_ts = to_unix(project_metadata.end_date)

		github_service = GitHubDataService()

		return github_service.fetch_repository_issues(
			github_metadata.owner_name,
			github_metadata.repo_name,
			start_ts,
			end_ts,
			github_metadata.project_board,
		)
	except ValidationError as e:
		ctx.logger.error(f"Validation error for GithubMetadata/ProjectMetadata: {e}")
		raise ValueError(f"Validation error: {e}")
	except KeyError as e:
		ctx.logger.error(f"Missing required field in event data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error in fetch_github: {e}")
		raise
