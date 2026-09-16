"""Parser for old format standup messages (DEPRECATED)."""

from app.slack.constants import OLD_FORMAT_PATTERNS
from app.slack.services.standup_parser.base import BaseParser


class OldFormatParser(BaseParser):
	"""Parser for old format standup messages (DEPRECATED).

	Deprecated: Use NewFormatParser instead.
	"""

	def __init__(self):
		"""Initialize parser with pre-normalized question patterns."""
		self.question_patterns = {
			key: [self.normalize_for_matching(p) for p in patterns]
			for key, patterns in OLD_FORMAT_PATTERNS.items()
		}

	def _should_strip_headers(self) -> bool:
		"""Retain markdown headers for legacy standup format."""
		return False

	def _should_skip_first_line(self, original_text: str) -> bool:
		"""Include the first line for legacy format parsing."""
		return False
