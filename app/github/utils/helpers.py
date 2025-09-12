from datetime import datetime

from app.github.utils.constants import BLOCKED_ISSUE_STATUS_NAME


def format_to_yymmdd(iso_date: str) -> str:
	"""Formats an ISO 8601 date string to 'YYYY-MM-DD'.
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
	"""
	Filters and processes GitHub issues for a specific project board.

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

		# Checks for Blocked issues on projectboard
		# Exclude comments from issues body for non-blocked issues.
		is_blocked = any(
			any(
				status.get("name") == BLOCKED_ISSUE_STATUS_NAME
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
