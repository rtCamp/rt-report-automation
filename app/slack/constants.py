"""Constants for Slack integration."""

# Allow 2 executions/minute - may occasionally hit conversations.replies
# 50+ RPM limit (60 calls total) but burst behavior should handle it.
SLACK_API_RATE_LIMIT = 2

# TODO(sainathpoojary): https://github.com/rtCamp/rt-report-automation/issues/11
# After standardizing the workflow name, update it here.
STANDUP_WORKFLOW_NAME = "AI Internal - Daily Tasks Tracker"

# Standardized question keys - always in the same order
STANDARD_QUESTIONS = [
	"yesterday",
	"today",
	"blockers",
	"demo",
]

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

# ============================================================================
# Old Format Constants (DEPRECATED)
# ============================================================================

# TODO(rutviksavsani): Remove old format constants once we have enough new format
# content to test LLM summarization and prompts. Necessary until then to ensure
# sufficient data for LLM processing.
# https://github.com/rtCamp/rt-report-automation/issues

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
