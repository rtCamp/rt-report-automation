"""Controller for LLM-related operations."""

import secrets
import uuid

import inngest
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.logger import logger

from app.core.adapters import inngest_client
from app.core.auth import validate_api_key
from app.core.config import settings
from app.core.exceptions import InternalServerError
from app.llm.models import (
	ModelResponse,
	SummarizeRequest,
	SummarizeResponse,
	SupportedModels,
)
from app.llm.websocket_manager import summarization_ws_manager

router = APIRouter(
	prefix="/llm",
	tags=["LLM Operations"],
)


@router.get(
	"/models",
	summary="List Supported Models",
	description="Retrieve a list of supported LLM models along with their details.",
	response_model=list[ModelResponse],
	dependencies=[Depends(validate_api_key)],
)
def list_supported_models():
	"""List all supported LLM models."""
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
	dependencies=[Depends(validate_api_key)],
)
async def summarize_text(request: SummarizeRequest):
	"""Trigger a summarization job with the provided data."""
	try:
		request_data = request.model_dump(mode="json")
		request_data["request_id"] = request_data.get("request_id") or str(uuid.uuid4())

		ids = await inngest_client.send(
			inngest.Event(
				name="rt-report-automation/summarization_workflow",
				data=request_data,
			),
		)

		return SummarizeResponse(
			request_id=request_data["request_id"],
			run_ids=ids,
		)
	except Exception as e:
		logger.error(f"Error sending event to Inngest: {e}")
		raise InternalServerError(
			error=e,
			message="Failed to send event to Inngest",
		)


@router.websocket("/summarize/ws/{request_id}")
async def summarize_websocket(websocket: WebSocket, request_id: str):
	"""WebSocket endpoint for summarization completion notifications."""
	# Validate API key from query params
	api_key = websocket.query_params.get("api_key", "")
	
	# Accept connection first (required by WebSocket protocol)
	await websocket.accept()
	
	# Then check authentication and close if invalid
	if not secrets.compare_digest(api_key, settings.APP_API_KEY.get_secret_value()):
		await websocket.close(code=1008, reason="Invalid API key")
		return

	# Register this connection (already accepted, so pass False)
	await summarization_ws_manager.connect(request_id=request_id, websocket=websocket, accept_connection=False)

	try:
		# Keep connection alive and listen for client disconnect
		while True:
			await websocket.receive_text()
	except WebSocketDisconnect:
		await summarization_ws_manager.disconnect(request_id=request_id, websocket=websocket)
