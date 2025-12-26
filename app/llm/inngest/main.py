"""Inngest workflow for LLM-based summarization."""

import json

import inngest

from app.core.adapters import inngest_client
from app.github.inngest import fetch_github_issues
from app.google_docs.inngest import generate_google_doc
from app.llm.inngest.summarization import summarization
from app.slack.inngest import fetch_slack


@inngest_client.create_function(
	fn_id="summarization_workflow",
	trigger=inngest.TriggerEvent(event="rt-report-automation/summarization_workflow"),
	retries=2,
)
async def summarization_workflow(ctx: inngest.Context) -> dict[str, str]:
	"""Inngest workflow function to fetch Slack and GitHub data to generate summaries.

	Orchestrates a four-step workflow:
	1. Fetches standup messages from Slack using the fetch_slack function
	2. Fetches GitHub issues using the fetch_github_issues function
	3. Summarizes the fetched data using LLM-based summarization (waits for completion)
	4. Generates a Google Doc from the summary (waits for completion)

	Args:
		ctx (inngest.Context): The Inngest context containing SummarizeRequest data:
			- llm_model_overrides (ModelMetadata): LLM model configuration
			- project_metadata (ProjectMetadata): Project details with start/end dates
			- user_metadata (UserMetadata): User information
			- github_metadata (GitHubMetadata): GitHub repository details
			- slack_metadata (SlackMetadata): Slack configuration with channel_slug

	Returns:
		dict[str, str]: Dictionary containing the generated Google Doc URL.
			Example: {"document_url": "https://docs.google.com/document/d/..."}

	Raises:
		Exception: Any errors from the fetch_slack, summarization, or Google Docs steps.

	"""
	(slack_data, github_issues_data) = await ctx.group.parallel(
		(
			lambda: ctx.step.invoke(
				"fetch_slack",
				function=fetch_slack,
				data=ctx.event.data,
			),
			lambda: ctx.step.invoke(
				"fetch_github_issues",
				function=fetch_github_issues,
				data=ctx.event.data,
			),
		),
	)

	# Convert github_issues_data to JSON string
	github_issues_data = json.dumps(github_issues_data)

	# Prepare data for the summarization step
	data = dict(ctx.event.data)
	data["data"] = [slack_data, github_issues_data]

	# Step 3: Generate summary using LLM
	summary_json = await ctx.step.invoke(
		"summarization",
		function=summarization,
		data=data,
	)

	# Step 4: Generate Google Doc from summary
	google_docs_data = {
		"summary_json": summary_json,
		"project_metadata": ctx.event.data.get("project_metadata"),
		"user_metadata": ctx.event.data.get("user_metadata"),
	}

	return await ctx.step.invoke(
		"generate_google_doc",
		function=generate_google_doc,
		data=google_docs_data,
	)
