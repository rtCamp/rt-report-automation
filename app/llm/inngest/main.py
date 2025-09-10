import inngest

from app.core.adapters import inngest_client
from app.llm.inngest.summarization import summarization


@inngest_client.create_function(
	fn_id="summarization_workflow",
	trigger=inngest.TriggerEvent(event="rt-report-automation/summarization_workflow"),
)
async def summarization_workflow(ctx: inngest.Context) -> str:
	return await ctx.step.invoke(
		"invoke",
		function=summarization,
		data=ctx.event.data,
	)
