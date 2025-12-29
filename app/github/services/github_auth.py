"""Authentication service layer for GitHub integration."""

import asyncio
import time
from datetime import UTC, datetime

import httpx
import jwt
from fastapi import HTTPException

from app.core.adapters.redis import redis_client
from app.core.config import settings
from app.core.exceptions import InternalServerError
from app.github.utils.constants import (
	GITHUB_ACCESS_TOKEN_KEY,
	GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS,
	GITHUB_TOKEN_REFRESH_LOCK_KEY,
	GITHUB_TOKEN_REFRESH_LOCK_TTL_SECONDS,
)


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

	async def get_access_token(self, *, force_refresh: bool = False) -> str:
		"""Exchange JWT for a GitHub App installation access token with a Redis lock.

		- Returns cached token if present and not forcing refresh.
		- If missing, acquires an NX lock so only one worker refreshes the token.
		- If lock is held, waits briefly for another worker to populate the token.

		Args:
			force_refresh (bool): Whether to force a token refresh.

		Raises:
			InternalServerError: If token refresh fails or times out.

		Returns:
			str: The GitHub installation access token.

		"""
		cached_token = redis_client.get(GITHUB_ACCESS_TOKEN_KEY)
		if cached_token is not None and not force_refresh:
			return str(cached_token)

		# If the caller forces refresh, clear any existing token first
		if force_refresh and cached_token is not None:
			redis_client.delete(GITHUB_ACCESS_TOKEN_KEY)

		# Try to acquire a short-lived refresh lock to prevent concurrent refreshes
		have_lock = redis_client.set(
			GITHUB_TOKEN_REFRESH_LOCK_KEY,
			"1",
			nx=True,
			ex=GITHUB_TOKEN_REFRESH_LOCK_TTL_SECONDS,
		)

		if not have_lock:
			# Another worker is refreshing; wait for the token to appear
			for _ in range(10):  # ~5 seconds total wait
				await asyncio.sleep(0.5)
				cached_token = redis_client.get(GITHUB_ACCESS_TOKEN_KEY)
				if cached_token:
					return str(cached_token)

			# Still no token available; surface a transient error
			raise InternalServerError(
				"Token refresh in progress",
				"Unable to read refreshed token from Redis",
			)

		# We have the lock; perform the token exchange
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

			# Calculate TTL in seconds with pre-refresh buffer
			ttl_seconds = int(
				(expiry_dt - datetime.now(UTC)).total_seconds()
				- GITHUB_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS,
			)

			# Ensure the TTL is positive; otherwise, treat the token as invalid
			if ttl_seconds <= 0:
				raise InternalServerError(
					"Received GitHub access token with non-positive TTL",
					"Token is already expired or expires within the configured buffer",
				)

			# Cache the token in Redis with a valid TTL
			redis_client.set(
				GITHUB_ACCESS_TOKEN_KEY,
				access_token_value,
				ttl_seconds,
			)

		return access_token_value
