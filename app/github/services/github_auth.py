"""Authentication service layer for GitHub integration."""

import time
from datetime import UTC, datetime

import httpx
import jwt
from fastapi import HTTPException

from app.core.adapters.redis import redis_client
from app.core.config import settings
from app.core.exceptions import InternalServerError
from app.github.utils.constants import GITHUB_ACCESS_TOKEN_KEY


class GitHubAuthService:
	"""Service for generating GitHub App JWT and installation access tokens."""

	def __init__(self):
		"""Initialize the GitHubAuthService."""
		self._signing_key: bytes | None = None

	@property
	def signing_key(self) -> bytes:
		"""Lazy load PEM key from environment variable."""
		if self._signing_key is None:
			key = settings.GITHUB_APP_PRIVATE_KEY.get_secret_value()
			self._signing_key = key.encode("utf-8")

		return self._signing_key

	def _generate_app_signed_jwt(self) -> str:
		"""Generate a JWT for GitHub App authentication."""
		try:
			current_time = int(time.time())
			expiration = settings.GITHUB_APP_SIGNED_JWT_TTL

			payload = {
				"iat": current_time,
				"exp": current_time + expiration,
				"iss": settings.GITHUB_CLIENT_ID.get_secret_value(),
			}

			return jwt.encode(payload, self.signing_key, algorithm="RS256")

		except Exception as error:
			raise InternalServerError(
				error,
				"Failed to generate JWT",
			)

	async def get_access_token(self) -> str:
		"""Exchange JWT for a GitHub App installation access token."""
		cached_token = redis_client.get(GITHUB_ACCESS_TOKEN_KEY)
		if cached_token is not None:
			return str(cached_token)

		jwt_token = self._generate_app_signed_jwt()
		installation_id = settings.GITHUB_INSTALLATION_ID.get_secret_value()
		url = (
			f"https://api.github.com/app/installations/{installation_id}/access_tokens"
		)
		headers = {
			"Authorization": f"Bearer {jwt_token}",
			"Accept": "application/vnd.github+json",
		}

		async with httpx.AsyncClient() as client:
			response = await client.post(url, headers=headers)

		if response.status_code != 201:
			raise HTTPException(
				status_code=response.status_code,
				detail=f"Failed to get installation token: {response.text}",
			)

		response_data = response.json()
		access_token_value = response_data.get("token")
		access_token_expiry = response_data.get("expires_at")

		if access_token_value and access_token_expiry:
			# Convert the ISO 8601 expiry string to a datetime object
			expiry_dt = datetime.fromisoformat(
				access_token_expiry.replace("Z", "+00:00"),
			)

			# Calculate TTL in seconds, subtract 60s buffer
			ttl_seconds = int(
				(expiry_dt - datetime.now(UTC)).total_seconds() - 60,
			)

			# Cache the token in Redis
			redis_client.set(
				GITHUB_ACCESS_TOKEN_KEY,
				access_token_value,
				ttl_seconds,
			)

		return access_token_value
