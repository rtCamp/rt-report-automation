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
	responses={
		200: {
			"description": "Inngest run status retrieved successfully",
			"content": {
				"application/json": {
					"example": {
						"data": [
							{
								"run_id": "01KPZ2GTK23KKQBD1Y3NYYHC8E",
								"run_started_at": "2026-04-24T06:23:32.962Z",
								"function_id": "9577baf4-7d44-572b-acb4-b04cf05e487d",
								"function_version": 0,
								"environment_id": "00000000-0000-0000-0000-000000000000",  # noqa: E501
								"event_id": "01KPZ2GTFVR7X2X4V0B1Q9QS6X",
								"status": "Completed",
								"ended_at": "2026-04-24T06:24:18.984143Z",
								"output": {
									"document_url": "https://docs.google.com/document/d/example/edit",
								},
							}
						],
						"metadata": {
							"fetched_at": "2026-04-24T12:29:19.445086Z",
							"cached_until": "2026-04-24T12:29:34.445086Z",
						},
					},
				},
			},
		}
	},
)
async def get_run_status(event_id: str):
	"""Proxy endpoint to check Inngest run status by event ID."""
	return await inngest_proxy_service.get_run_status(event_id)
