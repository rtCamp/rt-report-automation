"""Parser for old format standup messages (DEPRECATED).

TODO(rutviksavsani): Remove this parser once we have enough new format content to test
LLM summarization and prompts. The old parser is necessary until then to
ensure we have sufficient data for LLM processing. Use NewFormatParser instead.
https://github.com/rtCamp/rt-report-automation/issues
"""

from app.slack.constants import OLD_FORMAT_PATTERNS
from app.slack.services.standup_parser.base import BaseParser


class OldFormatParser(BaseParser):
	"""Parser for old format standup messages (DEPRECATED).

	This parser is kept for backward compatibility only.
	TODO(rutviksavsani): Remove once we have enough new format content to test LLM
	summarization and prompts. Necessary until then to ensure sufficient
	data for LLM processing.
	https://github.com/rtCamp/rt-report-automation/issues

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
