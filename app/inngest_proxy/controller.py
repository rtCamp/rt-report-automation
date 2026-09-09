"""Controller for proxying Inngest run-status requests."""

from fastapi import APIRouter

from app.inngest_proxy.models import RunStatusResponse
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
		"browser CORS restrictions, and normalizes the result into a "
		"toast-ready status with structured failure detail."
	),
	response_model=RunStatusResponse,
	response_model_exclude_none=False,
	responses={
		200: {
			"description": "Run status retrieved successfully",
			"content": {
				"application/json": {
					"examples": {
						"completed": {
							"summary": "Report generated",
							"value": {
								"event_id": "01KPZ2GTFVR7X2X4V0B1Q9QS6X",
								"run_id": "01KPZ2GTK23KKQBD1Y3NYYHC8E",
								"state": "completed",
								"status": "Completed",
								"is_terminal": True,
								"message": "Report generated successfully.",
								"document_url": "https://docs.google.com/document/d/example/edit",
								"error": None,
							},
						},
						"failed_user_fixable": {
							"summary": "Failed for a reason the PM can fix",
							"value": {
								"event_id": "01KPZ2GTFVR7X2X4V0B1Q9QS6X",
								"run_id": "01KPZ2GTK23KKQBD1Y3NYYHC8E",
								"state": "failed",
								"status": "Failed",
								"is_terminal": True,
								"message": (
									"The report bot does not have access to the "
									"Slack channel. Invite the bot to the channel, "
									"then try again."
								),
								"document_url": None,
								"error": {
									"error_code": "slack_access_denied",
									"user_message": (
										"The report bot does not have access to "
										"the Slack channel."
									),
									"action": (
										"Invite the bot to the channel, then try again."
									),
									"is_user_fixable": True,
									"technical_detail": "SlackApiError: not_in_channel",
									"trace_id": "01KPZ2GTK23KKQBD1Y3NYYHC8E",
									"occurred_at": "2026-04-24T06:24:18.984143Z",
								},
							},
						},
						"failed_unknown": {
							"summary": "Unrecognised failure, escalate with trace ID",
							"value": {
								"event_id": "01KPZ2GTFVR7X2X4V0B1Q9QS6X",
								"run_id": "01KPZ2GTK23KKQBD1Y3NYYHC8E",
								"state": "failed",
								"status": "Failed",
								"is_terminal": True,
								"message": (
									"Report generation failed for an unexpected "
									"reason. Share the trace ID with engineering "
									"so they can check the logs."
								),
								"document_url": None,
								"error": {
									"error_code": "unknown",
									"user_message": (
										"Report generation failed for an unexpected "
										"reason. Share the trace ID with engineering "
										"so they can check the logs."
									),
									"action": None,
									"is_user_fixable": False,
									"technical_detail": "RuntimeError: unexpected",
									"trace_id": "01KPZ2GTK23KKQBD1Y3NYYHC8E",
									"occurred_at": "2026-04-24T06:24:18.984143Z",
								},
							},
						},
					},
				},
			},
		}
	},
)
async def get_run_status(event_id: str) -> RunStatusResponse:
	"""Proxy endpoint to check Inngest run status by event ID."""
	return await inngest_proxy_service.get_run_status(event_id)
