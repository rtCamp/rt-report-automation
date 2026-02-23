"""Controller for proxying Inngest run-status requests."""

from fastapi import APIRouter

from app.inngest_proxy.service import InngestProxyService

router = APIRouter(
	prefix="/inngest",
	tags=["Inngest Proxy"],
)

inngest_proxy_service = InngestProxyService()


@router.get(
	"/runs/{event_id}",
	summary="Get Inngest Run Status",
	description=(
		"Check the status of an Inngest run by event ID. "
		"Proxies the request server-side to the Inngest API to avoid "
		"browser CORS restrictions."
	),
)
async def get_run_status(event_id: str):
	"""Proxy endpoint to check Inngest run status by event ID."""
	return await inngest_proxy_service.get_run_status(event_id)
