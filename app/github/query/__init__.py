"""GitHub query package initialization."""

from app.github.query.gql_queries import (
	get_audit_issue_fetch_query,
	get_issue_fetch_query,
	get_issue_search_query,
	get_multi_repo_open_issues_search_query,
)

__all__ = [
	"get_audit_issue_fetch_query",
	"get_issue_fetch_query",
	"get_issue_search_query",
	"get_multi_repo_open_issues_search_query",
]
