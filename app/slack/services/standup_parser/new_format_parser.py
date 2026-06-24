"""Parser for new format standup messages.

New format identifier: Messages starting with '# Daily update from'
"""

from app.slack.constants import NEW_FORMAT_IDENTIFIER, NEW_FORMAT_PATTERNS
from app.slack.services.standup_parser.base import BaseParser


class NewFormatParser(BaseParser):
	"""Parser for new format standup messages.

	New format messages start with '# Daily update from <@USER_ID>'
	and use ## headers for questions.
	"""

	def __init__(self):
		"""Initialize parser with pre-normalized question patterns."""
		self.question_patterns = {
			key: [self.normalize_for_matching(p) for p in patterns]
			for key, patterns in NEW_FORMAT_PATTERNS.items()
		}

	def is_new_format_message(self, message: dict) -> bool:
		"""Check if message uses the new format.

		Args:
			message: Slack message object.

		Returns:
			True if message uses new format, False otherwise.

		"""
		message_text = self.get_message_text(message)
		if not message_text.strip():
			return False

		normalized_identifier = NEW_FORMAT_IDENTIFIER.lower().strip()
		first_line = message_text.split("\n")[0].strip().lower()
		return first_line.startswith(normalized_identifier)

	def message_has_questions(self, message: dict) -> bool:
		"""Check if message should be parsed with NEW_FORMAT_PATTERNS.

		Accepts either:
		- canonical new-format header, or
		- any recognizable standard question from NEW_FORMAT_PATTERNS.
		"""
		if self.is_new_format_message(message):
			return True

		return super().message_has_questions(message)
