"""Data service layer for GitHub integration."""

import httpx

from app.core.adapters import redis_client
from app.core.config import settings
from app.core.exceptions import AuthenticationError, InternalServerError
from app.github.query import (
	get_audit_issue_fetch_query,
	get_issue_fetch_query,
	get_issue_search_query,
	get_multi_repo_open_issues_search_query,
)
from app.github.services.github_auth import GitHubAuthService
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
	) -> str:
		"""Fetch issues from a GitHub repository within a specific date range.

		Args:
			owner_name (str): The owner of the repository.
			repository_name (str): The name of the repository.
			start_date (str): The start date in ISO 8601 format (YYYY-MM-DD).
			end_date (str): The end date in ISO 8601 format (YYYY-MM-DD).
			project_board (str): The name of the project board to filter issues.

		Returns:
			str: A formatted string representation of the processed issues.

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
		retried_auth = False

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
					if response.status_code in (401, 403):
						redis_gh_access_token = redis_client.get(
							GITHUB_ACCESS_TOKEN_KEY,
						)
						# If the stored token matches, invalidate it
						if redis_gh_access_token == gh_access_token:
							redis_client.delete(GITHUB_ACCESS_TOKEN_KEY)

						if not retried_auth:
							# Force refresh token and retry once
							gh_access_token = await self.auth.get_access_token(
								force_refresh=True,
							)
							retried_auth = True
							continue

						raise AuthenticationError(
							"GitHub API unauthorized/forbidden after retry",
						)

					raise InternalServerError(
						f"{response.status_code} - {response.text}",
						"GitHub API error",
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

	async def fetch_open_issues_for_audit(
		self,
		repos: list[tuple[str, str]],
	) -> list[dict]:
		"""Fetch open issues across one or more repositories for /pms audit.

		Unlike `fetch_repository_issues`, this isn't scoped to a date range
		or a single repository, and it isn't paginated -- `first: 100` is
		GitHub's max page size, which doubles as the audit's item cap.

		Args:
			repos (list[tuple[str, str]]): (owner, repo) pairs to search
				across. All of a project's linked repos can be passed at
				once since GitHub ORs repeated `repo:` search qualifiers.

		Returns:
			list[dict]: Open issues with `number`, `title`, `url`, `status`,
				`start_date`, and `target_date` (the last three may be
				None if the corresponding project board field isn't set).

		"""
		if not repos:
			return []

		search_query = get_multi_repo_open_issues_search_query(repos)
		query_issues = get_audit_issue_fetch_query()
		gh_access_token = await self.auth.get_access_token()
		retried_auth = False

		async with httpx.AsyncClient() as client:
			while True:
				response = await client.post(
					str(settings.GITHUB_API_GQL_ENDPOINT),
					json={
						"query": query_issues,
						"variables": {"search_query": search_query},
					},
					headers={"Authorization": f"Bearer {gh_access_token}"},
				)

				if response.status_code != 200:
					if response.status_code in (401, 403):
						redis_gh_access_token = redis_client.get(
							GITHUB_ACCESS_TOKEN_KEY
						)
						if redis_gh_access_token == gh_access_token:
							redis_client.delete(GITHUB_ACCESS_TOKEN_KEY)

						if not retried_auth:
							gh_access_token = await self.auth.get_access_token(
								force_refresh=True,
							)
							retried_auth = True
							continue

						raise AuthenticationError(
							"GitHub API unauthorized/forbidden after retry",
						)

					raise InternalServerError(
						f"{response.status_code} - {response.text}",
						"GitHub API error",
					)

				data = response.json()
				break

		issue_nodes = data.get("data", {}).get("search", {}).get("nodes", [])
		return [_parse_audit_issue(node) for node in issue_nodes]


def _parse_audit_issue(node: dict) -> dict:
	"""Flatten a raw audit-query Issue node into number/title/url/status/dates.

	Field names in the GitHub Project board use title-case (e.g. "Start Date",
	"End Date") which can differ from what was originally hard-coded. To avoid
	another silent mismatch, all field names are normalised to lowercase before
	lookup, so "Start Date", "start date", or "START DATE" all resolve the same
	way. The board's "End Date" maps to `target_date` (the key the rest of the
	app already uses for the deadline column).
	"""
	# Normalise to lowercase so capitalisation differences don't break lookups.
	fields: dict[str, str | None] = {}
	for project_item in node.get("projectItems", {}).get("items", []):
		for field_value in project_item.get("fieldValues", {}).get("items", []):
			field_name = (field_value.get("field") or {}).get("name")
			if not field_name:
				continue
			fields[field_name.lower()] = field_value.get("name") or field_value.get(
				"date"
			)

	return {
		"number": node["number"],
		"title": node["title"],
		"url": node["url"],
		# "status" → single-select field named "Status"
		"status": fields.get("status"),
		# "start date" covers "Start Date", "start date", etc.
		"start_date": fields.get("start date"),
		# boards use "Target date" OR "End Date" — check both, prefer "target date"
		"target_date": fields.get("target date") or fields.get("end date"),
	}
