"""Helper functions for processing GitHub issues and project items."""

from datetime import datetime

from toon import encode

from app.github.utils.constants import (
	BLOCKED_ISSUE_STATUS_NAME,
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


def get_processed_issue_list(issues: list[dict], project_board: str) -> str:
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
		str: A formatted string representation of the processed issues.

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

	return encode(processed_issues)


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
