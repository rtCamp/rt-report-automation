from fastapi import APIRouter, Depends

from app.core.auth import validate_api_key

router = APIRouter(
	tags=["Health Check"],
)


@router.get(
	"/health",
	summary="Health Check",
	description="Check the health of the application",
	dependencies=[Depends(validate_api_key)],
)
async def health_check():
	return {"status": "API is healthy 🚀"}
