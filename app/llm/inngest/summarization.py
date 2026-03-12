"""Inngest function for LLM-based summarization using stuff/map-reduce strategy."""

import datetime

import inngest
from langchain.chat_models import init_chat_model
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langfuse import observe
from promptguard import PromptGuard, SanitizationStrategy
from pydantic import ValidationError

from app.core.adapters import inngest_client
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
async def summarization(ctx: inngest.Context) -> str:
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
		guard = PromptGuard()

		if not validate(docs_data, list):
			raise

		sanitized_docs = []
		for content in docs_data:
			validate(content, str)
			response = guard.sanitize(
				content,
				strategy=SanitizationStrategy.CONSERVATIVE,
			)
			sanitized_docs.append(response.sanitization.sanitized)
		docs_data = sanitized_docs

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
			[str(content) for content in docs_data],
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
			stuff_summarization_service = StuffService(llm=llm, docs=documents)
			return await stuff_summarization_service.summarize()

		map_reduce_service = MapReduceSummarizationService(
			llm=llm,
			docs=documents,
			max_tokens=max_allowed_tokens,
		)
		return await map_reduce_service.summarize()

	except ValidationError as e:
		ctx.logger.error(f"Validation error for ModelMetadata: {e}")
		raise ValueError(f"Invalid model metadata: {e}")
	except KeyError as e:
		ctx.logger.error(f"Missing required field in event data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error in summarization: {e}")
		raise
