from fastapi import APIRouter

router = APIRouter(
	tags=["Health Check"],
)


@router.get(
	"/health",
	summary="Health Check",
	description="Check the health of the application",
)
async def health_check():
	return {"status": "API is healthy 🚀"}
