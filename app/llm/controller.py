from fastapi import APIRouter

from app.llm.models import SummarizeRequest, SummarizeResponse

router = APIRouter(
	prefix="/llm",
	tags=["LLM Operations"],
)


@router.get(
	"/summarize",
	summary="Summarize Text",
	description="Run summarization on the provided data by triggering a job.",
	response_model=SummarizeResponse,
)
def summarize_text(request: SummarizeRequest):
	# Trigger the summarization job here.
	pass
