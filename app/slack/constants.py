"""Constants for Slack integration."""

# Allow 2 executions/minute - may occasionally hit conversations.replies
# 50+ RPM limit (60 calls total) but burst behavior should handle it.
SLACK_API_RATE_LIMIT = 2

# Echoed back by Slack on options requests and selections, so the interaction
# handler can tell this menu apart from any future one.
AUDIT_PROJECT_SELECT_ACTION_ID = "audit_project_select"

# Slack rejects the whole Block Kit payload if either is exceeded.
SLACK_OPTION_TEXT_LIMIT = 75
SLACK_MAX_SELECT_OPTIONS = 100

# Slack drops the options response at 3s; stay under it so a slow upstream
# yields an empty menu rather than nothing at all.
OPTIONS_TIME_BUDGET_SECONDS = 2.5

# /pms subcommands, and the usage text shown for anything else.
PMS_SUBCOMMANDS = frozenset({"projects", "missing-fields", "audit", "timesheets"})
PMS_USAGE_TEXT = (
	"Usage: `/pms projects`, `/pms missing-fields`, `/pms audit`, or "
	"`/pms timesheets`. `missing-fields` can optionally take a project name or "
	"ID to filter to a single project, e.g. `/pms missing-fields PROJ-0669`. "
	"`audit` opens a project picker, or takes an ID directly, e.g. "
	"`/pms audit PROJ-0669`. `timesheets` reviews time logs for members or "
	"projects over a date range; run it alone for details."
)

# /pms timesheets: selectable checks, and the longest range (in days,
# inclusive) one request may cover.
# A tuple, not a set: its order is the default `--checks` order and the order
# shown in the usage text.
TIMESHEET_CHECKS = (
	"duplicates",
	"incomplete",
	"estimates",
	"gaps",
	"contributions",
	"repeats",
	"setup",
	"docs",
)
TIMESHEET_MAX_RANGE_DAYS = 90
TIMESHEET_USAGE_TEXT = (
	"Usage: `/pms timesheets <analyze|fetch> (--members IDS | --projects IDS) "
	"--from YYYY-MM-DD --to YYYY-MM-DD [--checks CHECKS]`\n"
	"• `--members` / `--projects`: comma-separated IDs; use exactly one.\n"
	f"• `--from` / `--to`: inclusive, at most {TIMESHEET_MAX_RANGE_DAYS} days.\n"
	"• `--checks` (`analyze` only, defaults to all): "
	f"{', '.join(f'`{c}`' for c in TIMESHEET_CHECKS)}.\n"
	"Examples:\n"
	"`/pms timesheets analyze --members EMP-001,EMP-002 "
	"--from 2026-09-21 --to 2026-09-25`\n"
	"`/pms timesheets fetch --projects PROJ-0669 "
	"--from 2026-09-01 --to 2026-09-30`\n"
	"`/pms timesheets analyze --projects PROJ-0669 "
	"--from 2026-09-01 --to 2026-09-30 --checks duplicates,gaps`"
)

# A user ID maps to the same email indefinitely; cached to keep the lookup
# off the picker's per-keystroke path.
SLACK_USER_EMAIL_CACHE_KEY = "slack:user_email:{user_id}"
SLACK_USER_EMAIL_CACHE_TTL = 86400

# Legacy workflow name. Standup threads are now matched on the "standup" and
# "tracker" keywords in SlackService._filter_messages_by_workflow, so this
# exact name only still matters as a fallback for older messages posted
# before the naming was standardized.
STANDUP_WORKFLOW_NAME = "AI Internal - Daily Tasks Tracker"

# Standardized question keys - always in the same order
STANDARD_QUESTIONS = [
	"yesterday",
	"today",
	"blockers",
	"demo",
]

# Keyword anchors used to detect standup sections in legacy/old-format threads
# that do not contain NEW_FORMAT_IDENTIFIER. Matching is case-insensitive and
# checks whether a line contains any of these keywords as a section header.
KEYWORD_ANCHORS: dict[str, list[str]] = {
	"yesterday": ["yesterday"],
	"today": ["today"],
	"blockers": ["blocker", "blockers"],
	"demo": ["demo"],
}

# Parser thresholds (all measured in characters).
STANDUP_MIN_QUESTION_LINE_LENGTH = 10
STANDUP_MAX_HEADER_MATCH_OFFSET = 15
STANDUP_LONG_LINE_LENGTH_THRESHOLD = 100

# ============================================================================
# New Format Constants
# ============================================================================

# New format identifier - messages starting with this are in the new format
NEW_FORMAT_IDENTIFIER = "# Daily update from"

# New format question patterns
NEW_FORMAT_PATTERNS = {
	"yesterday": ["what did you work on yesterday"],
	"today": ["what will you be working on today"],
	"blockers": ["any blockers encountered"],
	"demo": ["anything youd like to demo internally"],
}

# Old format question patterns (DEPRECATED)
OLD_FORMAT_PATTERNS = {
	"yesterday": [
		"what you worked on yesterday",
		"what did you work on yesterday",
	],
	"today": [
		"what are you working on today",
		"what you are working on today",
	],
	"blockers": [
		"any blockers encountered or conversations needed",
		"any blockers encountered of conversations needed",
		"any blockers to conversations needed",
	],
	"demo": [
		"anything youd like to demo internally",
	],
}

# Combined patterns for backward compatibility (will be removed in future)
# Use NEW_FORMAT_PATTERNS or OLD_FORMAT_PATTERNS instead
QUESTION_PATTERNS = {
	key: list(
		dict.fromkeys(
			NEW_FORMAT_PATTERNS.get(key, []) + OLD_FORMAT_PATTERNS.get(key, [])
		),
	)
	for key in set(NEW_FORMAT_PATTERNS) | set(OLD_FORMAT_PATTERNS)
}

# Shown when the requester's Slack profile has no email -- shared by every
# command that must match the requester to a Next PMS user.
SLACK_EMAIL_UNREADABLE_TEXT = (
	"⚠️ Couldn't read your email from your Slack profile, so there's no "
	"way to match you to Next PMS.\n"
	"Add a work email to your Slack profile, then try again."
)
