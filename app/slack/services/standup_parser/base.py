"""Base parser with shared utilities for all format parsers."""

import re

from app.slack.constants import (
	NEW_FORMAT_IDENTIFIER,
	STANDUP_LONG_LINE_LENGTH_THRESHOLD,
	STANDUP_MAX_HEADER_MATCH_OFFSET,
	STANDUP_MIN_QUESTION_LINE_LENGTH,
)


class BaseParser:
	"""Base parser with shared utilities for text normalization and extraction."""

	# Concrete parsers populate `question_patterns` (as an instance attribute in
	# their own __init__) with the phrases that map to the canonical
	# STANDARD_QUESTIONS keys. Annotation only, no default -- BaseParser is
	# never instantiated directly, so there's no shared mutable dict to
	# accidentally leak state between parser instances.
	question_patterns: dict[str, list[str]]

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

		# Strip Slack artifacts so question matching operates on plain text.
		# Avoid routing tokens or formatting markers that skew detection.
		# - Mentions look like <@U123ABC>. They only reference a user and never contain
		#   question content, so we drop them entirely.
		text = re.sub(r"<@[A-Z0-9]+>", "", text)
		# - Channel references like <#C123|daily-standup> repeat their alias.
		#   Drop the wrapper to prevent duplicate text.
		text = re.sub(r"<#[A-Z0-9]+\|[^>]+>", "", text)
		# - Autolinks (<https://example.com|Example>) embed raw URLs that inflate lines.
		#   Remove the entire token.
		text = re.sub(r"<https?://[^>]+>", "", text)
		# - Code fences (```...```) usually contain logs unrelated to answers.
		#   Drop the fenced block wholesale.
		text = re.sub(r"```[\s\S]*?```", "", text)
		# - Inline code segments (`snippet`) are stripped.
		#   Only the inner content remains.
		text = re.sub(r"`[^`]+`", "", text)
		# - Emphasis markers (*bold*, _italic_) should not create duplicate characters.
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
		# Drop common bullet symbols (hyphen, dot, unicode bullets) at the start.
		line = re.sub(r"^[-•\u2022\u25e6\u25aa\ufe0e]\s*", "", line)
		# Remove ordered-list prefixes such as "1." or "2)" before the answer text.
		line = re.sub(r"^\d+[\.\)]\s*", "", line)
		# Strip leftover emphasis markers so only the content remains.
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

		match element_type:
			case "text":
				return element.get("text", "")
			case "link":
				return element.get("text", element.get("url", ""))
			case "rich_text_section":
				return "".join(
					self._extract_text_from_element(sub)
					for sub in element.get("elements", [])
				)
			case "rich_text_list":
				list_items = [
					self._extract_text_from_element(item).strip()
					for item in element.get("elements", [])
				]
				return "\n".join(item for item in list_items if item)
			case _:
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
		"""Normalize text for question matching with optional header stripping.

		Example:
			Before::
				"## WHAT did you work on yesterday?"

			After::
				"what did you work on yesterday"

		This makes legacy/new format patterns case-insensitive and resilient to
		Slack formatting artifacts.

		"""
		if not text:
			return ""

		if strip_headers is None:
			strip_headers = self._should_strip_headers()

		text = text.lower()
		text = text.replace("\u2019", "'").replace("\u2018", "'")
		# Remove emphasis markers so matching runs on plain words.
		text = re.sub(r"[*_]+", "", text)
		# Collapse contractions like "what's" -> "whats" for consistent comparison.
		text = re.sub(r"(\w+)'([a-z]+)", r"\1\2", text)
		if strip_headers:
			text = re.sub(r"^#+\s*", "", text)
		# Drop punctuation except whitespace so only word characters remain.
		text = re.sub(r"[^\w\s]", "", text)
		# Remove ordered-list prefixes ("1.", "2)") when matching question lines.
		text = re.sub(r"^\d+[\.\)]\s*", "", text)
		text = re.sub(r"\s+", " ", text)
		return text.strip()

	def _should_strip_headers(self) -> bool:
		"""Return the parser-specific default for header stripping.

		Subclasses override this to opt in/out without mutating shared state, and
		every call to ``normalize_for_matching`` can still provide an explicit
		``strip_headers`` override when needed.
		"""
		return True

	def _should_skip_first_line(self, original_text: str) -> bool:
		"""Whether to skip the first line when preparing lines.

		Computed per message instead of via a static class attribute so that
		parsers can decide dynamically (e.g., new format uses a header line while
		legacy format keeps it).
		"""
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
			if self.get_question_key(line.strip()):
				return True
		return False

	def prepare_lines(self, text: str) -> list[str]:
		"""Prepare normalized lines for downstream parsing.

		Example:
			Input::
				# Daily update from <@U123>
				## What did you work on yesterday?
				- Wrapped up API work

			Output::
				[
					"## What did you work on yesterday?",
					"- Wrapped up API work",
				]

		"""
		should_skip = self._should_skip_first_line(text)
		normalized_text = self._normalize_text(text, preserve_newlines=True)
		lines = normalized_text.split("\n")
		if should_skip and lines:
			return lines[1:]
		return lines

	def get_question_key(self, line: str) -> str | None:
		"""Return the matched question key if the line identifies a question."""
		normalized = self.normalize_for_matching(
			line,
			strip_headers=self._should_strip_headers(),
		)
		if not normalized or len(normalized) < STANDUP_MIN_QUESTION_LINE_LENGTH:
			return None

		for question_key, patterns in self.question_patterns.items():
			for pattern in patterns:
				pos = normalized.find(pattern)
				if pos >= 0 and (
					pos <= STANDUP_MAX_HEADER_MATCH_OFFSET
					or len(normalized) < STANDUP_LONG_LINE_LENGTH_THRESHOLD
				):
					return question_key
		return None

	def _commit_current_answer(
		self,
		result: dict[str, list[str]],
		current_question: str | None,
		current_answer_lines: list[str],
	) -> list[str]:
		"""Append accumulated answer lines and reset the buffer."""
		if current_question and current_answer_lines:
			answer_text = "\n".join(current_answer_lines).strip()
			if answer_text:
				result.setdefault(current_question, []).append(answer_text)
			return []
		return current_answer_lines

	def _extract_inline_answer(
		self,
		original_line: str,
		question_key: str,
	) -> str | None:
		"""Return an answer that appears on the same line as the question."""
		# Split on the first '?' or ':' to capture inline answers after the question,
		# even when no space follows the separator.
		after_separators = re.split(r"[?:]\s*", original_line, maxsplit=1)
		if len(after_separators) <= 1:
			return None

		after_question = after_separators[1].strip()
		if not after_question:
			return None

		normalized_after = self.normalize_for_matching(after_question)
		patterns = self.question_patterns.get(question_key, [])
		if any(p in normalized_after for p in patterns):
			return None

		cleaned = self._clean_answer_line(after_question)
		return cleaned or None

	def parse_message_text(self, text: str) -> dict[str, list[str]]:
		"""Parse normalized text into structured question -> answers mapping."""
		result: dict[str, list[str]] = {}
		current_question: str | None = None
		current_answer_lines: list[str] = []

		for original_line in self.prepare_lines(text):
			line = original_line.strip()
			if not line or line == "---":
				continue

			question_key = self.get_question_key(line)

			if question_key:
				current_answer_lines = self._commit_current_answer(
					result,
					current_question,
					current_answer_lines,
				)
				current_question = question_key

				inline_answer = self._extract_inline_answer(original_line, question_key)
				if inline_answer:
					current_answer_lines.append(inline_answer)
				continue

			if current_question:
				cleaned_line = self._clean_answer_line(line)
				if cleaned_line:
					current_answer_lines.append(cleaned_line)

		current_answer_lines = self._commit_current_answer(
			result,
			current_question,
			current_answer_lines,
		)

		return result
