from fastapi import APIRouter

from app.github.service import GitHubAuthService

router = APIRouter(
	prefix="/gh",
	tags=["GH Operations"],
)


@router.get(
	"/access_token",
	summary="Access Token",
	description="Get access token for GitHub App installation",
)
async def get_access_token():
	service = GitHubAuthService()
	return await service.get_access_token()
