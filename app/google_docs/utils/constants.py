"""Constants for Google Docs integration."""

# Tag formatting
TAG_PREFIX = "rtai-"
TAG_SUFFIX = "-rtai"

# Validation limits
MAX_REPLACEMENT_ENTRIES = 100  # Maximum number of replacement key-value pairs

# Folder management
DEFAULT_MAX_RECURSION_DEPTH = 10  # Maximum depth for recursive folder search

# TODO(namankhare): https://github.com/rtCamp/rt-report-automation/issues/67
# The folder name is subject to change and will be updated once the final
# naming decision is made.
AUTOMATED_DOCS_FOLDER_NAME = "Automated Docs"


def get_template_tag(key: str) -> str:
	"""Generate a template tag for replacements.

	Args:
		key: The key for the template tag. Must be non-empty and
			contain only alphanumeric characters, hyphens, underscores, and spaces.

	Returns:
		The formatted template tag.

	Raises:
		ValueError: If key is empty or contains invalid characters.

	"""
	if not key or not key.strip():
		raise ValueError("Template tag key cannot be empty")

	# Allow alphanumeric, hyphens, underscores, and spaces
	if not all(c.isalnum() or c in "-_ " for c in key):
		raise ValueError(
			f"Template tag key '{key}' contains invalid characters. "
			"Only alphanumeric, hyphens, underscores, and spaces are allowed.",
		)

	# Use triple braces to create literal braces in the formatted string
	# Format: {{{rtai-key-rtai}}} where outer braces escape to create literal {
	# This produces: {{{rtai-projectName-rtai}}} in the Google Doc template
	return f"{{{{{{{TAG_PREFIX}{key}{TAG_SUFFIX}}}}}}}"
