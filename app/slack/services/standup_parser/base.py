"""Base parser with shared utilities for all format parsers."""

import re

from app.slack.constants import NEW_FORMAT_IDENTIFIER


class BaseParser:
	"""Base parser with shared utilities for text normalization and extraction."""

	# Parameters tuned for Slack standup question detection:
	# - MIN_QUESTION_LINE_LENGTH: skip short noise lines (bullets, greetings, etc.).
	# - MAX_HEADER_MATCH_OFFSET: treat matches near the start of the line as headers.
	# - LONG_LINE_LENGTH_THRESHOLD: relax the offset constraint for verbose lines where
	MIN_QUESTION_LINE_LENGTH = 10
	MAX_HEADER_MATCH_OFFSET = 15
	LONG_LINE_LENGTH_THRESHOLD = 100
	question_patterns: dict[str, list[str]] = {}

	def _normalize_text(self, text: str, *, preserve_newlines: bool = False) -> str:
		"""Normalize Slack message text by removing formatting.

		Args:
			text: Raw Slack message text.
			preserve_newlines: If True, preserve newlines in the text.

		Returns:
			Normalized text with formatting removed.

		"""
		if not text:
			return ""

		text = re.sub(r"<@[A-Z0-9]+>", "", text)
		text = re.sub(r"<#[A-Z0-9]+\|[^>]+>", "", text)
		text = re.sub(r"<https?://[^>]+>", "", text)
		text = re.sub(r"```[\s\S]*?```", "", text)
		text = re.sub(r"`[^`]+`", "", text)
		text = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", text)

		if preserve_newlines:
			text = re.sub(r"[ \t]+", " ", text)
			text = re.sub(r" *\n *", "\n", text)
			text = text.strip()
		else:
			text = re.sub(r"\s+", " ", text)
			text = text.strip()

		return text

	def _clean_answer_line(self, line: str) -> str:
		"""Clean answer line by removing bullet prefixes and formatting.

		Args:
			line: Answer line to clean.

		Returns:
			Cleaned answer text.

		"""
		line = line.lstrip("\t ")
		line = re.sub(r"^[-•\u2022\u25e6\u25aa\ufe0e]\s*", "", line)
		line = re.sub(r"^\d+[\.\)]\s*", "", line)
		line = re.sub(r"[*_]+", "", line)

		return line.strip()

	def _extract_text_from_element(self, element: dict) -> str:
		"""Extract text from a Slack block element recursively.

		Args:
			element: Slack block element.

		Returns:
			Extracted text from the element.

		"""
		element_type = element.get("type")

		if element_type == "text":
			return element.get("text", "")
		if element_type == "link":
			return element.get("text", element.get("url", ""))
		if element_type == "rich_text_section":
			return "".join(
				self._extract_text_from_element(sub)
				for sub in element.get("elements", [])
			)
		if element_type == "rich_text_list":
			list_items = [
				self._extract_text_from_element(item).strip()
				for item in element.get("elements", [])
			]
			return "\n".join(item for item in list_items if item)

		return ""

	def get_message_text(self, message: dict) -> str:
		"""Extract text from a Slack message (blocks or text field).

		Args:
			message: Slack message object.

		Returns:
			Extracted text, empty string if no content.

		"""
		blocks = message.get("blocks", [])
		text = message.get("text", "").strip()

		if blocks:
			return self._extract_text_from_blocks(blocks)
		return text

	def _extract_text_from_blocks(self, blocks: list[dict]) -> str:
		"""Extract plain text from Slack blocks structure.

		Args:
			blocks: Slack blocks structure.

		Returns:
			Plain text with structure preserved (newlines).

		"""
		text_parts = []

		for block in blocks:
			if block.get("type") == "rich_text":
				for element in block.get("elements", []):
					element_text = self._extract_text_from_element(element)
					if element_text.strip():
						text_parts.append(element_text.strip())
			elif block.get("type") == "rich_text_section":
				section_text = self._extract_text_from_element(block)
				if section_text.strip():
					text_parts.append(section_text.strip())

		return "\n".join(text_parts)

	def normalize_for_matching(
		self,
		text: str,
		*,
		strip_headers: bool | None = None,
	) -> str:
		"""Normalize text for question matching with optional header stripping."""
		if not text:
			return ""

		if strip_headers is None:
			strip_headers = self._should_strip_headers()

		text = text.lower()
		text = text.replace("\u2019", "'").replace("\u2018", "'")
		text = re.sub(r"[*_]+", "", text)
		text = re.sub(r"(\w+)'([a-z]+)", r"\1\2", text)
		if strip_headers:
			text = re.sub(r"^#+\s*", "", text)
		text = re.sub(r"[^\w\s]", "", text)
		text = re.sub(r"^\d+[\.\)]\s*", "", text)
		text = re.sub(r"\s+", " ", text)
		return text.strip()

	def _should_strip_headers(self) -> bool:
		"""Whether to strip markdown headers when normalizing question lines."""
		return True

	def _should_skip_first_line(self, original_text: str) -> bool:
		"""Whether to skip the first line when preparing lines."""
		if not original_text:
			return False

		lines = original_text.split("\n")
		if not lines:
			return False

		first_line = lines[0].strip().lower()
		normalized_identifier = NEW_FORMAT_IDENTIFIER.lower().strip()
		return first_line.startswith(normalized_identifier)

	def message_has_questions(self, message: dict) -> bool:
		"""Determine whether the message contains any recognizable questions."""
		message_text = self.get_message_text(message)
		if not message_text.strip():
			return False

		for line in self.prepare_lines(message_text):
			if self.is_question_line(line.strip()):
				return True
		return False

	def prepare_lines(self, text: str) -> list[str]:
		"""Prepare normalized lines for downstream parsing."""
		should_skip = self._should_skip_first_line(text)
		normalized_text = self._normalize_text(text, preserve_newlines=True)
		lines = normalized_text.split("\n")
		if should_skip and lines:
			return lines[1:]
		return lines

	def is_question_line(self, line: str) -> str | None:
		"""Identify the question key using parameters for short, early matches."""
		normalized = self.normalize_for_matching(
			line,
			strip_headers=self._should_strip_headers(),
		)
		if not normalized or len(normalized) < self.MIN_QUESTION_LINE_LENGTH:
			return None

		for question_key, patterns in self.question_patterns.items():
			for pattern in patterns:
				pos = normalized.find(pattern)
				if pos >= 0 and (
					pos <= self.MAX_HEADER_MATCH_OFFSET
					or len(normalized) < self.LONG_LINE_LENGTH_THRESHOLD
				):
					return question_key
		return None

	def parse_message_text(self, text: str) -> dict[str, list[str]]:
		"""Parse normalized text into structured question -> answers mapping."""
		result: dict[str, list[str]] = {}
		current_question: str | None = None
		current_answer_lines: list[str] = []

		for original_line in self.prepare_lines(text):
			line = original_line.strip()
			if not line or line == "---":
				continue

			question_key = self.is_question_line(line)

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
						normalized_after = self.normalize_for_matching(after_question)
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
