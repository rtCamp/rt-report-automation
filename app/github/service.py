import time
from datetime import UTC, datetime

import httpx
import jwt
from fastapi import HTTPException

from app.core.adapters.redis import redis_client
from app.core.config import settings
from app.core.exceptions import InternalServerError
from app.github.query.gql_queries import get_issue_fetch_query, get_issue_search_query


class GitHubAuthService:
	"""Service for generating GitHub App JWT and installation access tokens."""

	def __init__(self):
		self._signing_key: bytes | None = None
		self.access_token_key: str = "github_access_token"

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
		cached_token = redis_client.get(self.access_token_key)
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
				self.access_token_key,
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
						curr_access_token = redis_client.get(self.auth.access_token_key)

						if curr_access_token != gh_access_token:
							gh_access_token = curr_access_token
						else:
							redis_client.delete(self.auth.access_token_key)
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

			processed_issues: list[dict] = []

			for item in issues:
				project_items = []
				for project_item in item.get("projectItems", {}).get("items", []):
					if project_item.get("project", {}).get("title") == project_board:
						field_values = project_item.get("fieldValues")
						if field_values:
							# Projectboard status name filtering to remove empty{}
							# objects
							filtered_items = [
								proj_status
								for proj_status in field_values.get("items", [])
								if "name" in proj_status
							]
							project_item = {
								**project_item,
								"fieldValues": {
									**field_values,
									"items": filtered_items,
								},
							}
						if project_item.get("fieldValues", {}).get("items"):
							project_items.append(project_item)

				# Checks for Blocked issues on projectboard
				# Exclude comments from issues body for non-blocked issues.
				is_blocked = any(
					any(
						status.get("name") == "Blocked"
						for status in proj.get("fieldValues", {}).get("items", [])
					)
					for proj in project_items
				)

				# Extract selected properties
				comments = item.get("comments")
				labels = item.get("labels")
				cross_referenced_prs = item.get("crossReferencedPRs")

				# Filters the raw issue object to exclude the fields listed below.
				# The excluded fields will be processed and appended to the dict later.
				rest = {
					key: value
					for key, value in item.items()
					if key not in ["comments", "labels", "crossReferencedPRs"]
				}

				processed_item = {**rest}

				# Add labels if present and non-empty
				if labels and labels.get("items"):
					processed_item["labels"] = labels

				# Add crossReferencedPRs only if items exist and the item has pr_id
				if cross_referenced_prs:
					items = cross_referenced_prs.get("items", [])
					if items and items[0].get("source").get("pr_id"):
						processed_item["crossReferencedPRs"] = cross_referenced_prs

				# Always include projectItems with filtered items
				processed_item["projectItems"] = {
					**item.get("projectItems", {}),
					"items": project_items,
				}

				# Add comments only if issue is blocked
				if is_blocked:
					processed_item["comments"] = comments

				if project_items:
					processed_issues.append(processed_item)

			return processed_issues
