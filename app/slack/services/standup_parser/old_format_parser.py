"""Parser for old format standup messages (DEPRECATED).

TODO(rutviksavsani): Remove this parser once we have enough new format content to test
LLM summarization and prompts. The old parser is necessary until then to
ensure we have sufficient data for LLM processing. Use NewFormatParser instead.
https://github.com/rtCamp/rt-report-automation/issues
"""

import re

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
		# Pre-normalize patterns for faster matching
		self.question_patterns = {
			key: [self._normalize_for_matching(p) for p in patterns]
			for key, patterns in OLD_FORMAT_PATTERNS.items()
		}

	def _normalize_for_matching(self, text: str) -> str:
		"""Normalize text for question pattern matching.

		Args:
			text: Raw text to normalize.

		Returns:
			Normalized text ready for pattern matching.

		"""
		if not text:
			return ""

		text = text.lower()
		text = text.replace("\u2019", "'").replace("\u2018", "'")
		text = re.sub(r"[*_]+", "", text)
		text = re.sub(r"(\w+)'([a-z]+)", r"\1\2", text)
		text = re.sub(r"[^\w\s]", "", text)
		text = re.sub(r"^\d+[\.\)]\s*", "", text)
		text = re.sub(r"\s+", " ", text)

		return text.strip()

	def _message_has_questions(self, message: dict) -> bool:
		"""Check if a message contains any questions (old format).

		Args:
			message: Slack message object.

		Returns:
			True if message contains at least one question.

		"""
		message_text = self._get_message_text(message)
		if not message_text.strip():
			return False

		return any(
			self._is_question_line(line.strip()) for line in message_text.split("\n")
		)

	def _is_question_line(self, line: str) -> str | None:
		"""Check if a line matches a known question pattern.

		Args:
			line: Line to check for question patterns.

		Returns:
			Question key if match found, None otherwise.

		"""
		normalized = self._normalize_for_matching(line)
		if not normalized or len(normalized) < 10:
			return None

		for question_key, patterns in self.question_patterns.items():
			for pattern in patterns:
				pos = normalized.find(pattern)
				if pos >= 0 and (pos <= 15 or len(normalized) < 100):
					return question_key

		return None

	def _parse_message_text(self, text: str) -> dict[str, list[str]]:
		"""Parse message text into structured Q&A pairs (old format).

		Args:
			text: Message text to parse.

		Returns:
			Mapping of question_key -> list of answer strings.

		"""
		result: dict[str, list[str]] = {}
		current_question: str | None = None
		current_answer_lines: list[str] = []

		normalized_text = self._normalize_text(text, preserve_newlines=True)

		for line in normalized_text.split("\n"):
			original_line = line
			line = line.strip()

			if not line or line == "---":
				continue

			question_key = self._is_question_line(line)

			if question_key:
				if current_question and current_answer_lines:
					answer_text = "\n".join(current_answer_lines).strip()
					if answer_text:
						result.setdefault(current_question, []).append(answer_text)
					current_answer_lines = []

				current_question = question_key

				after_separators = re.split(r"[?:]\s+", original_line, maxsplit=1)
				if len(after_separators) > 1:
					after_question = after_separators[1].strip()
					if after_question:
						normalized_after = self._normalize_for_matching(after_question)
						patterns = self.question_patterns[question_key]
						if not any(p in normalized_after for p in patterns):
							cleaned = self._clean_answer_line(after_question)
							if cleaned:
								current_answer_lines.append(cleaned)
			else:
				if current_question:
					cleaned_line = self._clean_answer_line(line)
					if cleaned_line:
						current_answer_lines.append(cleaned_line)

		if current_question and current_answer_lines:
			answer_text = "\n".join(current_answer_lines).strip()
			if answer_text:
				result.setdefault(current_question, []).append(answer_text)

		return result
