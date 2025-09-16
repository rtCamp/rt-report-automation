"""Data service layer for GitHub integration."""

import httpx

from app.core.adapters import redis_client
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.github.query import get_issue_fetch_query, get_issue_search_query
from app.github.services import GitHubAuthService
from app.github.utils.constants import GITHUB_ACCESS_TOKEN_KEY
from app.github.utils.helpers import get_processed_issue_list


class GitHubDataService:
	"""Service for interacting with GitHub API to fetch repository data."""

	def __init__(self):
		"""Initialize the GitHubDataService."""
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
		query_issues = get_issue_fetch_query(include_comments=True)
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
						redis_gh_access_token = redis_client.get(
							GITHUB_ACCESS_TOKEN_KEY,
						)

						# If the stored token is invalid, delete it from Redis
						if redis_gh_access_token == gh_access_token:
							redis_client.delete(GITHUB_ACCESS_TOKEN_KEY)

						raise AuthenticationError(
							"""GitHub GraphQL API returned 401 Unauthorized""",
						)

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
