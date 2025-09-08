import time

import httpx
import jwt
from fastapi import HTTPException

from app.core.config import settings
from app.utils.custom_errors import InternalServerError


class GitHubAuthService:
	"""Service for generating GitHub App JWT and installation access tokens."""

	def __init__(self):
		self._signing_key: bytes | None = None

	@property
	def signing_key(self) -> bytes:
		"""Lazy load PEM key from environment variable."""
		if self._signing_key is None:
			key = settings.GITHUB_APP_PRIVATE_KEY.get_secret_value()
			self._signing_key = key.encode("utf-8")

		return self._signing_key

	def generate_installation_token(self) -> str:
		"""Generate a JWT for GitHub App authentication."""
		try:
			current_time = int(time.time())
			expiration = settings.GITHUB_INSTALLATION_TOKEN_TTL

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
				"Check the private key and client ID env.",
			)

	async def get_access_token(self) -> dict:
		"""Exchange JWT for a GitHub App installation access token."""
		jwt_token = self.generate_installation_token()
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

		return response.json()
