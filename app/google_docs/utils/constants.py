"""Constants for Google Docs integration."""

# Tag formatting
TAG_PREFIX = "rtai-"
TAG_SUFFIX = "-rtai"
DEFAULT_DOC_NAME = "Generated Document"


def get_template_tag(key: str) -> str:
	"""Generate a template tag for replacements.

	Args:
		key: The key for the template tag.

	Returns:
		The formatted template tag.

	"""
	return f"{{{{{{{TAG_PREFIX}{key}{TAG_SUFFIX}}}}}}}"
