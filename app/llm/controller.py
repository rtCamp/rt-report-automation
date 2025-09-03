from fastapi import APIRouter

router = APIRouter(
	prefix="/llm",
	tags=["LLM Operations"],
)


@router.get(
	"/summarize",
	summary="Summarize Text",
	description="Summarize the provided text using LLM",
)
async def summarize_text(text: str):
	pass
