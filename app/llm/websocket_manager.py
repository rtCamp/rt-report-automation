"""WebSocket connection management for LLM workflow notifications."""

import asyncio

from fastapi import WebSocket


class SummarizationWebSocketManager:
	"""Manage WebSocket clients subscribed by summarization request ID."""

	def __init__(self):
		"""Initialize manager state."""
		self._connections: dict[str, set[WebSocket]] = {}
		self._lock = asyncio.Lock()

	async def connect(self, request_id: str, websocket: WebSocket, accept_connection: bool = True):
		"""Accept and register a WebSocket for a request ID.
		
		Args:
			request_id: The unique request identifier
			websocket: The WebSocket connection
			accept_connection: Whether to accept the websocket (set False if already accepted)
		"""
		if accept_connection:
			await websocket.accept()

		async with self._lock:
			if request_id not in self._connections:
				self._connections[request_id] = set()
			self._connections[request_id].add(websocket)

	async def disconnect(self, request_id: str, websocket: WebSocket):
		"""Unregister a WebSocket for a request ID."""
		async with self._lock:
			request_connections = self._connections.get(request_id)
			if not request_connections:
				return

			request_connections.discard(websocket)
			if not request_connections:
				self._connections.pop(request_id, None)

	async def publish_completion(self, request_id: str, payload: dict):
		"""Send completion payload to all connected clients for request ID."""
		async with self._lock:
			request_connections = list(self._connections.get(request_id, set()))

		if not request_connections:
			return

		message = {
			"event": "summarization_completed",
			"request_id": request_id,
			"data": payload,
		}

		for websocket in request_connections:
			try:
				await websocket.send_json(message)
			except Exception:
				await self.disconnect(request_id, websocket)


summarization_ws_manager = SummarizationWebSocketManager()