"""Base parser with shared utilities for all format parsers."""

import re


class BaseParser:
	"""Base parser with shared utilities for text normalization and extraction."""

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

	def _get_message_text(self, message: dict) -> str:
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
