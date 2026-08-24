"""Inngest function for LLM-based summarization using stuff/map-reduce strategy."""

import asyncio
import datetime
import json

import inngest
from langchain.chat_models import init_chat_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langfuse import observe
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.core.sanitizers import sanitize_prompt
from app.core.services import PIIAnonymizer
from app.core.utils import validate
from app.llm.inngest.constants import (
	CHUNK_OVERLAP,
	CHUNK_SIZE,
	MIN_PROVIDER_API_RATE_LIMIT,
)
from app.llm.models.summarization import ModelMetadata
from app.llm.services import MapReduceSummarizationService, StuffService


@inngest_client.create_function(
	fn_id="summarization",
	trigger=inngest.TriggerEvent(event="rt-report-automation/summarization"),
	retries=2,
	throttle=inngest.Throttle(
		limit=MIN_PROVIDER_API_RATE_LIMIT,
		period=datetime.timedelta(minutes=1),
	),
)
@observe(name="summarization_workflow")
async def summarization(ctx: inngest.Context) -> str | dict | list:
	"""Inngest function to perform map-reduce style summarization.

	Args:
		ctx (inngest.Context): The Inngest context.
			- llm_model_overrides (dict): Model metadata
			- data (list[str]): List of contents to summarize

	Returns:
		str: The final summary.

	Raises:
		ValueError: If validation fails or required fields are missing.
		Exception: For any other errors during processing.

	"""
	try:
		event_data = ctx.event.data

		# Extract llm_model_overrides and data.
		llm_model_data = event_data.get("llm_model_overrides", {})
		docs_data = event_data.get("data", [])
		previous_report = event_data.get("previous_report")

		if not validate(docs_data, list):
			raise TypeError(f"Expected list for 'data', got {type(docs_data).__name__}")

		for content in docs_data:
			validate(content, str)

		# Offload synchronous CPU-bound PII anonymization to a thread-pool worker
		# so the event loop is not blocked during spaCy/Presidio processing.
		# Uses anonymize_with_mapping for reversible anonymization — the same
		# instance tracks consistent placeholders across all documents.
		pii_anonymizer = PIIAnonymizer()
		loop = asyncio.get_running_loop()
		validated_docs: list[str] = [str(content) for content in docs_data]

		def _anonymize_all() -> tuple[list[str], str | None]:
			anonymized = [
				pii_anonymizer.anonymize_with_mapping(doc) for doc in validated_docs
			]
			anonymized_prev = (
				pii_anonymizer.anonymize_with_mapping(str(previous_report))
				if previous_report
				else None
			)
			return anonymized, anonymized_prev

		anonymized_docs, anonymized_previous_report = await loop.run_in_executor(
			None,
			_anonymize_all,
		)

		sanitized_docs = [sanitize_prompt(content) for content in anonymized_docs]
		sanitized_previous_report = (
			sanitize_prompt(anonymized_previous_report)
			if anonymized_previous_report
			else None
		)

		llm_model_overrides = ModelMetadata.model_validate(llm_model_data)

		llm = init_chat_model(
			llm_model_overrides.model.value,
			model_provider=llm_model_overrides.provider.value,
			temperature=llm_model_overrides.temperature,
		)

		text_splitter = RecursiveCharacterTextSplitter(
			chunk_size=CHUNK_SIZE,
			chunk_overlap=CHUNK_OVERLAP,
		)

		documents = text_splitter.create_documents(
			[str(content) for content in sanitized_docs],
		)

		total_tokens = 0
		token_limit_exceeded = False

		# Use 60% of the context window to account for prompt/output overhead.
		max_allowed_tokens = int(llm_model_overrides.model.get_context_size() * 0.6)

		for doc in documents:
			total_tokens += llm.get_num_tokens(doc.page_content)
			if total_tokens > max_allowed_tokens:
				token_limit_exceeded = True
				break

		if not token_limit_exceeded:
			stuff_summarization_service = StuffService(
				llm=llm,
				docs=documents,
				previous_report=sanitized_previous_report,
			)
			result = await stuff_summarization_service.summarize()
		else:
			map_reduce_service = MapReduceSummarizationService(
				llm=llm,
				docs=documents,
				max_tokens=max_allowed_tokens,
				previous_report=sanitized_previous_report,
			)
			result = await map_reduce_service.summarize()

		# Parse the JSON result first, then de-anonymize on the parsed
		# data structure to avoid injecting unescaped characters into raw
		# JSON text (e.g. quotes or backslashes in original PII values).
		try:
			parsed = json.loads(result)
		except (json.JSONDecodeError, TypeError):
			parsed = result
		return PIIAnonymizer.deanonymize(parsed, pii_anonymizer.mapping)

	except ValidationError as e:
		ctx.logger.error(f"Validation error for ModelMetadata: {e}")
		raise ValueError(f"Invalid model metadata: {e}")
	except KeyError as e:
		ctx.logger.error(f"Missing required field in event data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error in summarization: {e}")
		raise
