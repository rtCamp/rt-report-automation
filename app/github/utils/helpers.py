"""Helper functions for processing GitHub issues and project items."""

from datetime import datetime
from typing import Any

from app.github.utils.constants import ( 
	BLOCKED_ISSUE_STATUS_NAME,
	DEFAULT_VALUE,
)



def format_to_yymmdd(iso_date: str) -> str:
	"""Format an ISO 8601 date string to 'YYYY-MM-DD'.

	Args:
		iso_date (str): The date string in ISO 8601 format.

	Returns:
		str: The formatted date string in 'YYYY-MM-DD' format.

	"""
	date = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))

	yy = date.year
	mm = f"{date.month:02d}"
	dd = f"{date.day:02d}"

	return f"{yy}-{mm}-{dd}"


def get_processed_issue_list(issues: list[dict], project_board: str) -> list[dict]:
	"""Filter and process GitHub issues for a specific project board.

	- Keeps only project items belonging to the given project board.
	- Removes empty status items from project fields.
	- Determines if the issue is "Blocked".
	- Adds comments only for blocked issues.
	- Preserves labels and cross-referenced PRs if present.

	Args:
		issues (list[dict]): Raw issues fetched from GitHub GraphQl API.
		project_board (str): Name of the project board to filter issues.

	Returns:
		list[dict]: Processed and filtered issues.

	"""
	processed_issues: list[dict] = []

	for item in issues:
		project_items = filter_project_items(item, project_board)
		if not project_items:
			continue

		# Checks for Blocked issues on projectboard
		# Exclude comments from issues body for non-blocked issues.
		is_blocked = any(
			any(
				status.get("name") == BLOCKED_ISSUE_STATUS_NAME
				for status in proj.get("fieldValues", {}).get("items", [])
			)
			for proj in project_items
		)
		processed_item = build_processed_issue_data(
			item=item,
			project_items=project_items,
			is_blocked=is_blocked,
		)
		processed_issues.append(processed_item)

	processed_issues = transform_to_llm_text(processed_issues) # type: ignore
	return processed_issues


def filter_project_items(item: dict, project_board: str) -> list[dict]:
	"""Filter and return project items associated with a specific project board.

	Args:
		item (dict): The raw GitHub issue/PR item data containing `projectItems`.
		project_board (str): The title of the project board to filter items for.

	Returns:
		list[dict]: A list of filtered project items belonging to the given
		project board, with cleaned `fieldValues`.

	"""
	project_items = []
	for project_item in item.get("projectItems", {}).get("items", []):
		if project_item.get("project", {}).get("title") == project_board:
			field_values = project_item.get("fieldValues")
			if field_values:
				# Projectboard status name filtering to remove empty
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

	return project_items


def build_processed_issue_data(
	*,
	item: dict,
	project_items: list[dict],
	is_blocked: bool,
) -> dict:
	"""Build a processed issue dictionary with filtered and reformatted fields.

	Args:
		item (dict): The raw GitHub issue data.
		project_items (list[dict]): Filtered project items to include.
		is_blocked (bool): Whether the issue is blocked. If True, comments
			are included.

	Returns:
		dict: A cleaned and structured issue dictionary containing the
		processed fields.

	"""
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
		if items and items[0].get("source", {}).get("pr_id"):
			processed_item["crossReferencedPRs"] = cross_referenced_prs

	# Always include projectItems with filtered items
	processed_item["projectItems"] = {
		**item.get("projectItems", {}),
		"items": project_items,
	}

	# Add comments only if issue is blocked
	if is_blocked:
		processed_item["comments"] = comments

	return processed_item


def resolve_path(data: Any, path_list: list[str]) -> Any | None:
    """Safely navigate nested dictionary keys.

    Args:
        data: The data structure to navigate (typically a dict).
        path_list: List of keys to traverse.

    Returns:
        The value at the end of the path, or None if any key is missing.
    """
    for key in path_list:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


def extract_list_values(data: dict, root_key: str, sub_path: list[str]) -> str:
    """Extract and concatenate values from GitHub's nested 'items' lists.

    Handles structures like crossReferencedPRs, labels, comments, etc.

    Args:
        data: The parent dictionary containing the items list.
        root_key: The key of the list container (e.g., "labels", "comments").
        sub_path: Path to navigate within each item.

    Returns:
        Pipe-separated string of extracted values, or "None" if empty.
    """
    items = resolve_path(data, [root_key, "items"])
    if not items or not isinstance(items, list):
        return DEFAULT_VALUE

    extracted = []
    for item in items:
        value = resolve_path(item, sub_path)
        if value:
            extracted.append(str(value))

    return " | ".join(extracted) if extracted else DEFAULT_VALUE


def transform_to_llm_text(issue_list: list[dict]) -> str:
    """Transform structured issue data into LLM-optimized text format.

    Args:
        issue_list: List of processed issue dictionaries.

    Returns:
        Formatted string with issue details separated by "===" markers.
    """
    if not issue_list:
        return ""

    output_blocks = []

    for issue in issue_list:
        # 1. Direct Field Extraction
        title = issue.get("title", DEFAULT_VALUE)
        state = issue.get("state", DEFAULT_VALUE)
        url = issue.get("url", DEFAULT_VALUE)
        updated = issue.get("updatedAt", DEFAULT_VALUE)
        repo = resolve_path(issue, ["repository", "name"]) or DEFAULT_VALUE

        # 2. List Extraction (Labels & PRs)
        labels = extract_list_values(issue, "labels", ["name"])
        prs = extract_list_values(issue, "crossReferencedPRs", ["source", "title"])
        comments = extract_list_values(issue, "comments", ["body"])

        # 3. Deep Nested Extraction (Status & Project)
        project_title = DEFAULT_VALUE
        status = DEFAULT_VALUE
        project_items = resolve_path(issue, ["projectItems", "items"])

        if project_items and len(project_items) > 0:
            item = project_items[0]
            project_title = resolve_path(item, ["project", "title"]) or DEFAULT_VALUE

            # Search for the Status field
            field_values = resolve_path(item, ["fieldValues", "items"]) or []
            for field_value in field_values:
                if resolve_path(field_value, ["field", "name"]) == "Status":
                    status = field_value.get("name", DEFAULT_VALUE)
                    break

        # 4. Constructing the Text Block (Token Optimized)
        block = (
            f"title: {title}, state: {state}\n"
            f"repo: {repo}, project: {project_title}\n"
            f"status: {status}\n"
            f"labels: {labels}\n"
            f"PRs: {prs}\n"
            f"url: {url}\n"
            f"comments: {comments}\n"
            f"date: {updated}"
        )
        output_blocks.append(block)

    return "\n\n===\n\n".join(output_blocks)
