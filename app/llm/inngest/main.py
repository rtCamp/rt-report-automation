import json

import inngest

from app.core.adapters import inngest_client
from app.llm.inngest.summarization import summarization
from app.slack.inngest.slack import fetch_slack


@inngest_client.create_function(
	fn_id="summarization_workflow",
	trigger=inngest.TriggerEvent(event="rt-report-automation/summarization_workflow"),
	retries=2,
)
async def summarization_workflow(ctx: inngest.Context) -> str:
	slack_data = await ctx.step.invoke(
		"fetch_slack",
		function=fetch_slack,
		data=ctx.event.data,
	)

	# Convert slack_data to JSON string
	slack_data = json.dumps(slack_data)

	# Prepare data for the summarization step
	data = dict(ctx.event.data)
	data["data"] = [slack_data]

	return await ctx.step.invoke(
		"invoke",
		function=summarization,
		data=data,
	)
