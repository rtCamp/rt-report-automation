import inngest
from langchain.chat_models import init_chat_model
from langchain.schema import Document
from pydantic import ValidationError

from app.core.adapters import inngest_client
from app.llm.models.summarization import ModelMetadata
from app.llm.services import MapReduceSummarizationService, StuffService

MAX_ALLOWED_TOKENS = 100_000


@inngest_client.create_function(
	fn_id="summarization",
	trigger=inngest.TriggerEvent(event="rt-report-automation/summarization"),
)
async def summarization(ctx: inngest.Context) -> str:
	"""Inngest function to perform map-reduce style summarization.

	Args:
		ctx (inngest.Context): The Inngest context.
			- llm_model_overrides (dict): Model metadata
			- data (list[str]): List of contents to summarize

	Returns:
		str: The final summary.
	"""
	try:
		event_data = ctx.event.data
		if not isinstance(event_data, dict):
			raise TypeError(
				f"Expected dict for event data, got {type(event_data).__name__}",
			)

		# Extract llm_model_overrides and data.
		llm_model_data = event_data.get("llm_model_overrides")
		docs_data = event_data.get("data", [])

		# Validate llm_model_data is a dict.
		if not isinstance(llm_model_data, (dict, type(None))):
			raise TypeError(
				f"Expected dict or None, got {type(llm_model_data).__name__}",
			)

		# Validate docs_data is a list.
		if not isinstance(docs_data, list):
			raise TypeError(
				f"Expected list for 'data', got {type(docs_data).__name__}",
			)

		# Validate each item in docs_data is a string.
		for i, content in enumerate(docs_data):
			if not isinstance(content, str):
				raise TypeError(
					f"Expected string at index {i}, got {type(content).__name__}",
				)

		llm_model_overrides = ModelMetadata.model_validate(llm_model_data)
		llm = init_chat_model(
			llm_model_overrides.model_name.value,
			model_provider=llm_model_overrides.provider.value,
			temperature=llm_model_overrides.temperature,
		)

		documents: list[Document] = [
			Document(page_content=str(content)) for content in docs_data
		]

		total_tokens = sum(llm.get_num_tokens(doc.page_content) for doc in documents)

		if total_tokens < MAX_ALLOWED_TOKENS:
			stuff_summarization_service = StuffService(llm=llm, docs=documents)
			return await stuff_summarization_service.summarize()

		map_reduce_service = MapReduceSummarizationService(llm=llm, docs=documents)
		return await map_reduce_service.summarize()

	except ValidationError as e:
		ctx.logger.error(f"Validation error for ModelMetadata: {e}")
		raise ValueError(f"Invalid model metadata: {e}")
	except KeyError as e:
		ctx.logger.error(f"Missing required field in event data: {e}")
		raise ValueError(f"Missing required field: {e}")
	except Exception as e:
		ctx.logger.error(f"Error in map_reduce_summarization: {e}")
		raise
