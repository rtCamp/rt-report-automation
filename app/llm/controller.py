import inngest
from fastapi import APIRouter
from fastapi.logger import logger

from app.core.adapters import inngest_client
from app.core.exceptions import InternalServerError
from app.llm.models import (
	ModelResponse,
	SummarizeRequest,
	SummarizeResponse,
	SupportedModels,
)

router = APIRouter(
	prefix="/llm",
	tags=["LLM Operations"],
)


@router.get(
	"/models",
	summary="List Supported Models",
	description="Retrieve a list of supported LLM models along with their details.",
	response_model=list[ModelResponse],
)
def list_supported_models():
	return [
		ModelResponse(
			name=model.value,
			context_window=model.get_context_size(),
			max_output_tokens=model.get_max_output_tokens(),
		)
		for model in SupportedModels
	]


@router.post(
	"/summarize",
	summary="Summarize Text",
	description="Run summarization on the provided data by triggering a job.",
	response_model=SummarizeResponse,
)
async def summarize_text(request: SummarizeRequest):
	try:
		ids = await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/summarization_workflow",
				data=request.model_dump(mode="json"),
			),
		)

		return SummarizeResponse(
			run_ids=ids,
		)
	except Exception as e:
		logger.error(f"Error sending event to Inngest: {e}")
		raise InternalServerError(
			error=e,
			message="Failed to send event to Inngest",
		)
