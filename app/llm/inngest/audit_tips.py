"""Inngest function for LLM-generated /pms audit tips."""

import asyncio
import datetime
import json

import inngest
from langchain.chat_models import init_chat_model
from langfuse import observe

from app.core.adapters import inngest_client
from app.core.sanitizers import sanitize_prompt
from app.core.services import PIIAnonymizer
from app.core.utils import validate
from app.llm.inngest.constants import MIN_PROVIDER_API_RATE_LIMIT
from app.llm.models import LLMProvider, SupportedModels
from app.llm.services import AuditTipsService

# Lower than the summarization default (0.7) -- tips should read stable and
# consistent across runs, not creative.
_AUDIT_TIPS_TEMPERATURE = 0.3


@inngest_client.create_function(
	fn_id="generate_audit_tips",
	trigger=inngest.TriggerEvent(event="rt-report-automation/generate_audit_tips"),
	# Modest retry count -- this runs inline on a user-facing Slack response
	# path, and the caller already falls back to hardcoded copy on failure.
	retries=1,
	throttle=inngest.Throttle(
		limit=MIN_PROVIDER_API_RATE_LIMIT,
		period=datetime.timedelta(minutes=1),
	),
)
@observe(name="audit_tips_workflow")
async def generate_audit_tips(ctx: inngest.Context) -> dict:
	"""Inngest function to generate business-value-framed tips for /pms audit.

	Args:
		ctx (inngest.Context): The Inngest context containing event.data with:
			- audit_data (dict): The project's milestones/todos/risks/
				github_issues, as built by `_build_audit_report`.

	Returns:
		dict: Parsed `AuditTipsSchema` fields (milestonesTip, todosTip,
			risksTip, githubTip), any of which may be None.

	Raises:
		ValueError: If required fields are missing from event data.
		Exception: For any other errors during tip generation.

	"""
	try:
		event_data = ctx.event.data
		validate(event_data, dict)

		audit_data = event_data["audit_data"]
		validate(audit_data, dict)

		# Offload synchronous CPU-bound PII anonymization to a thread-pool
		# worker, same pattern as the summarization pipeline.
		pii_anonymizer = PIIAnonymizer()
		loop = asyncio.get_running_loop()
		raw_json = json.dumps(audit_data)

		def _anonymize() -> str:
			return pii_anonymizer.anonymize_with_mapping(raw_json)

		anonymized_json = await loop.run_in_executor(None, _anonymize)
		sanitized_json = sanitize_prompt(anonymized_json)

		llm = init_chat_model(
			SupportedModels.GEMINI_2_5_FLASH.value,
			model_provider=LLMProvider.GOOGLE_GENAI.value,
			temperature=_AUDIT_TIPS_TEMPERATURE,
		)

		service = AuditTipsService(llm=llm, audit_data_json=sanitized_json)
		result_json = await service.generate()

		parsed = json.loads(result_json)
		return PIIAnonymizer.deanonymize(parsed, pii_anonymizer.mapping)

	except KeyError as e:
		ctx.logger.error(f"Missing required field in event data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error in generate_audit_tips: {e}")
		raise
