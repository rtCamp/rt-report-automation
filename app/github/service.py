import time
from datetime import UTC, datetime

import httpx
import jwt
from fastapi import HTTPException

from app.core.adapters.redis import redis_client
from app.core.config import settings
from app.core.exceptions import AuthenticationError, InternalServerError
from app.github.query.gql_queries import get_issue_fetch_query, get_issue_search_query
from app.github.utils.constants import GITHUB_ACCESS_TOKEN_KEY, MAX_RETRIES_ATTEMPT
from app.github.utils.helpers import get_processed_issue_list


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


class GitHubDataService:
	"""Service for interacting with GitHub API to fetch repository data."""

	def __init__(self):
		self.auth = GitHubAuthService()

	async def fetch_repository_issues(
		self,
		owner_name,
		repository_name,
		start_date,
		end_date,
		project_board,
	) -> list[dict]:
		"""Fetch issues from a GitHub repository within a specific date range.

		Args:
			owner_name (str): The owner of the repository.
			repository_name (str): The name of the repository.
			start_date (str): The start date in ISO 8601 format (YYYY-MM-DD).
			end_date (str): The end date in ISO 8601 format (YYYY-MM-DD).
			project_board (str): The name of the project board to filter issues.
		Returns:
			list: A list of issues matching the criteria.
		"""
		search_query = get_issue_search_query(
			owner_name,
			repository_name,
			start_date,
			end_date,
		)
		query_issues = get_issue_fetch_query(comments=True)
		issues: list[dict] = []
		issues_pagination_cursor: str | None = None
		gh_access_token = await self.auth.get_access_token()
		max_retries = MAX_RETRIES_ATTEMPT  # Max retries for overcoming 401 code.
		retries = 0  # Counter for 401 responses

		async with httpx.AsyncClient() as client:
			while True:
				response = await client.post(
					str(settings.GITHUB_API_GQL_ENDPOINT),
					json={
						"query": query_issues,
						"variables": {
							"search_query": search_query,
							"after": issues_pagination_cursor,
						},
					},
					headers={"Authorization": f"Bearer {gh_access_token}"},
				)

				if response.status_code != 200:
					if response.status_code == 401:
						if retries >= max_retries:
							raise AuthenticationError(
								"""GitHub GraphQl API returned 401 Unauthorized
								after max retries""",
							)
						retries += 1

						curr_access_token = redis_client.get(GITHUB_ACCESS_TOKEN_KEY)

						if curr_access_token != gh_access_token:
							gh_access_token = curr_access_token
						else:
							redis_client.delete(GITHUB_ACCESS_TOKEN_KEY)
							gh_access_token = await self.auth.get_access_token()
						continue

					raise Exception(
						f"GitHub API error: {response.status_code} - {response.text}",
					)
				data = response.json()

				search_data = data.get("data", {}).get("search")
				if not search_data:
					break

				issues.extend(search_data.get("nodes", []))

				page_info = search_data.get("pageInfo", {})
				if not page_info.get("hasNextPage"):
					break

				issues_pagination_cursor = page_info.get("endCursor")

			return get_processed_issue_list(issues, project_board)
