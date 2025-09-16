"""GraphQL queries for GitHub issues."""

from app.github.utils.helpers import format_to_yymmdd


def get_issue_fetch_query(*, include_comments: bool = False) -> str:
	"""Generate a GraphQL query string to fetch GitHub issues.

	Args:
		include_comments (bool): If True, the query will fetch the first 100 comments.
		Defaults to False.

	Returns:
		str: A GraphQL query string.

	"""
	comments_fragment = (
		"""
				comments(first: 100) {
				items: nodes {
					author {
					login
					}
					body
					createdAt
					updatedAt
					url
				}
				}
		"""
		if include_comments
		else ""
	)

	return f"""
	query ($search_query: String!, $after: String) {{
		search(query: $search_query, type: ISSUE, first: 100, after: $after) {{
			pageInfo {{
			hasNextPage
			endCursor
			}}
			nodes {{
			... on Issue {{
				number
				title
				state
				url
				updatedAt
				repository {{
				owner {{
					login
				}}
				name
				}}
				labels(first: 50) {{
				items: nodes {{
					name
				}}
				}}
				crossReferencedPRs: timelineItems(
				first: 50
				itemTypes: [CROSS_REFERENCED_EVENT]
				) {{
				items: nodes {{
					... on CrossReferencedEvent {{
					source {{
						... on PullRequest {{
						pr_id: number
						title
						url
						}}
					}}
					}}
				}}
				}}
				projectItems(first: 50) {{
				items: nodes {{
					id
					project {{
					title
					number
					}}
					fieldValues(first: 50) {{
					items: nodes {{
						# Single-select fields (e.g. Status, Priority, etc.)
						... on ProjectV2ItemFieldSingleSelectValue {{
						name
						field {{
							... on ProjectV2SingleSelectField {{
							name
							}}
						}}
						}}
					}}
					}}
				}}
				}}
				{comments_fragment}
			}}
			}}
		}}
		}}
		"""


def get_issue_search_query(
	owner: str,
	repo: str,
	start_date: str,
	end_date: str,
) -> str:
	"""Generate a GitHub issue search query string for GraphQL.

	Builds a search query that targets issues in a specific repository
	and filters them by their `updated` date range.

	Args:
		owner (str): The owner of the repository.
		repo (str): The name of the repository.
		start_date (str): Start date in ISO 8601 format (YYYY-MM-DD).
		end_date (str): End date in ISO 8601 format (YYYY-MM-DD).

	Returns:
		str: A formatted GitHub issue search query string.

	"""
	query = "repo:{owner}/{repo} is:issue updated:{start_date}..{end_date}"
	return query.format(
		owner=owner,
		repo=repo,
		start_date=format_to_yymmdd(start_date),
		end_date=format_to_yymmdd(end_date),
	)
