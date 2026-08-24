"""Constants for Frappe PMS integration."""

# Frappe doctype and field used to match a project to its manager's email.
# In Frappe, a User's `name` is their email address, so this Link field
# value IS the manager's email directly.
PROJECT_DOCTYPE = "Project"
PROJECT_MANAGER_FIELD = "custom_project_manager"
# Labeled "Lead Engineer" in the Next PMS UI, "Engineering Manager" in Frappe.
PROJECT_ENGINEERING_MANAGER_FIELD = "custom_engineering_manager"

# Grants /pms audit access to any project by exact ID, even if not its PM.
DELIVERY_MANAGER_ROLE = "Delivery Manager"
USER_DOCTYPE = "User"

PROJECT_BILLING_TYPE_FIELD = "custom_billing_type"
NON_BILLABLE_TYPE = "Non-Billable"

# Deny-list (not allow-list) so any other active status still gets audited;
PROJECT_SUPPRESSED_STATUSES = {"On hold", "Completed", "Cancelled"}

# Fields reported by the /pms missing-fields command, grouped into sections
# to mirror the Next PMS frontend's project detail layout. Each entry is
# (fieldname, label, icon). "Primary location" is intentionally omitted --
# it isn't a direct Project field (likely comes from the linked Customer).
PROJECT_DETAIL_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
	(
		"Specifics",
		[
			("priority", "Priority", "📊"),
			("custom_complexity", "Complexity", "🧩"),
			("custom_key_account", "Key Account", "🔑"),
			("custom_host", "Host", "🖥️"),
		],
	),
	(
		"Sourcing",
		[
			("custom_source", "Source", "🔍"),
			("custom_previous_cms", "Previous CMS", "🏷️"),
		],
	),
	(
		"Communication",
		[
			("custom_client_point_of_contact", "Point of Contact", "👤"),
			("frequency", "Time Report Frequency", "📅"),
		],
	),
	(
		"Marketing",
		[
			("custom_permission_for_case_study", "Case Study Approved", "📄"),
		],
	),
]

# Check-type (boolean) fields: Frappe stores these as 0/1, and 0 is a real
# "No" rather than a missing value, so they're never flagged as "missing"
# and always render as Yes/No rather than being left blank.
BOOLEAN_FIELDS = {
	"custom_permission_for_case_study",
}

# Flattened (fieldname, label) pairs across all sections -- used to build
# the Frappe API `fields` param and the compact multi-project missing list.
PROJECT_DETAIL_FIELDS: list[tuple[str, str]] = [
	(fieldname, label)
	for _, fields in PROJECT_DETAIL_SECTIONS
	for fieldname, label, _ in fields
]

# Milestones: Project Timeline Item (the ?tab=calendar source). Todos: the
# standalone ToDo doctype. Risk has no due-date field of its own.
PROJECT_TIMELINE_ITEM_DOCTYPE = "Project Timeline Item"
TODO_DOCTYPE = "ToDo"
RISK_DOCTYPE = "Risk"
GITHUB_REPOSITORY_DOCTYPE = "GitHub Repository"

# Next PMS's "Team members" list has no dedicated field -- it's derived from
# DocShare: everyone the project is shared with, minus PM and Lead Engineer.
DOCSHARE_DOCTYPE = "DocShare"

# Retainer classification -- Project.custom_billing_type value set.
RETAINER_BILLING_TYPE = "Retainer"
FIXED_COST_BILLING_TYPE = "Fixed Cost"
TIME_AND_MATERIAL_BILLING_TYPE = "Time and Material"

# Child table on Project listing the billable team (distinct from Resource
# Allocation, which covers all resourcing, billable or not).
PROJECT_BILLING_TEAM_FIELD = "custom_project_billing_team"
PROJECT_BILLING_TEAM_DOCTYPE = "Project Billing Team"

# Child table on Project tracking hours purchased/consumed/remaining per
# budget cycle. Shown as "Contracts" in the Next PMS Tracking tab.
PROJECT_BUDGET_FIELD = "custom_project_budget_hours"
PROJECT_BUDGET_DOCTYPE = "Project Budget"

# Standard ERPNext field computed from Sales Orders, plus custom
# lifetime-value fields. Shown as "Total project value" in Next PMS.
CONTRACT_VALUE_FIELD = "total_sales_amount"
LIFETIME_VALUE_TO_DATE_FIELD = "custom_lifetime_value_to_date"
EXPECTED_LIFETIME_VALUE_FIELD = "custom_expected_lifetime_value"
LIFETIME_VALUE_VS_BILLED_FIELD = "custom_lifetime_value_vs_billed_amount"

TASK_CLOSED_STATUSES = {"Completed", "Cancelled"}
# The ToDo doctype uses its own status vocabulary (Open/Closed/Cancelled)
# rather than Task's -- "Closed" is normalized to "Completed" when merged into a Task
# shaped record so the shared closed-status check above still applies.
TODO_STATUS_TO_TASK_STATUS = {"Closed": "Completed"}
RISK_MITIGATED_STATUS = "Mitigated"
RISK_BLOCKED_STATUS = "Blocked"
# Lower sorts first: escalate High-risk items to the top of the open-risk list.
RISK_LEVEL_ORDER = {"High": 0, "Medium": 1, "Low": 2}
