"""Service layer for proxying requests to the Inngest API."""

import logging

import httpx

from app.core.config import settings
from app.core.utils import log_and_raise
from app.inngest_proxy.constants import INNGEST_API_BASE_URL, INNGEST_API_TIMEOUT

logger = logging.getLogger(__name__)


class InngestProxyService:
	"""Service for proxying status requests to the Inngest REST API."""

	def __init__(self):
		"""Initialize the InngestProxyService."""
		self.signing_key = settings.INNGEST_SIGNING_KEY.get_secret_value()

	async def get_run_status(self, event_id: str) -> dict:
		"""Fetch run status from the Inngest API for a given event ID.

		Args:
			event_id (str): The Inngest event ID to look up.

		Returns:
			dict: The JSON response from the Inngest API.

		Raises:
			HTTPException: If the Inngest API returns an error or is unreachable.

		"""
		url = f"{INNGEST_API_BASE_URL}/events/{event_id}/runs"

		try:
			async with httpx.AsyncClient() as client:
				response = await client.get(
					url,
					headers={"Authorization": f"Bearer {self.signing_key}"},
					timeout=INNGEST_API_TIMEOUT,
				)
				response.raise_for_status()
				return response.json()
		except httpx.HTTPStatusError as exc:
			log_and_raise(
				logger,
				f"Inngest API returned HTTP {exc.response.status_code}",
				http_status_code=502,
				cause=exc,
			)
		except Exception as exc:
			log_and_raise(
				logger,
				"Failed to check run status from Inngest",
				http_status_code=502,
				cause=exc,
			)
