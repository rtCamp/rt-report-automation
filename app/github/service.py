import time

import httpx
import jwt
from fastapi import HTTPException

from app.core.config import settings


class GitHubAuthService:
	"""Service for generating GitHub App JWT and installation access tokens."""

	def __init__(self, settings=settings):
		self.settings = settings
		self._signing_key: bytes | None = None

	@property
	def signing_key(self) -> bytes:
		"""Lazy load PEM key from environment variable."""
		if self._signing_key is None:
			try:
				key = self.settings.GITHUB_APP_PRIVATE_KEY.get_secret_value()
				self._signing_key = key.encode("utf-8")
			except Exception as e:
				raise HTTPException(
					status_code=500,
					detail=f"Error loading PEM from env: {str(e)}",
				)
		return self._signing_key

	def generate_refresh_token(self, custom_expiration: int | None = None) -> str:
		"""Generate a JWT for GitHub App authentication."""
		try:
			print(self.settings.GITHUB_REFRESH_TOKEN_TTL)
			current_time = int(time.time())
			expiration = custom_expiration or self.settings.GITHUB_REFRESH_TOKEN_TTL

			payload = {
				"iat": current_time,
				"exp": current_time + expiration,
				"iss": self.settings.GITHUB_CLIENT_ID.get_secret_value(),
			}

			return jwt.encode(payload, self.signing_key, algorithm="RS256")

		except Exception as e:
			raise HTTPException(
				status_code=500,
				detail=f"Failed to generate JWT: {str(e)}",
			)

	async def get_access_token(self) -> dict:
		"""Exchange JWT for a GitHub App installation access token."""
		jwt_token = self.generate_refresh_token()

		url = f"https://api.github.com/app/installations/{self.settings.GITHUB_INSTALLATION_ID.get_secret_value()}/access_tokens"
		headers = {
			"Authorization": f"Bearer {jwt_token}",
			"Accept": "application/vnd.github+json",
		}
		print(url)

		async with httpx.AsyncClient() as client:
			response = await client.post(url, headers=headers)

		if response.status_code != 201:
			raise HTTPException(
				status_code=response.status_code,
				detail=f"Failed to get installation token: {response.text}",
			)

		return response.json()
