"""Service for parsing Slack standup threads into structured data.

This module provides a unified parser interface that automatically
detects and routes to the appropriate format parser (new or old).
"""

from collections import defaultdict
from datetime import UTC, datetime

from toon import encode as process_json_to_toon

from app.slack.constants import KEYWORD_ANCHORS, STANDARD_QUESTIONS
from app.slack.models.models import DailyUpdateEntry, DailyUpdateQuestionAnswer
from app.slack.services.standup_parser.base import BaseParser
from app.slack.services.standup_parser.new_format_parser import NewFormatParser
from app.slack.services.standup_parser.old_format_parser import OldFormatParser


class StandupParser:
	"""Unified parser that auto-detects format and routes to appropriate parser.

	Automatically detects whether a message uses the new format (starts with
	'# Daily update from') or old format, and uses the appropriate parser.
	"""

	def __init__(self):
		"""Initialize parser with both format parsers."""
		self._new_parser = NewFormatParser()
		# TODO(rutviksavsani): Remove old parser once we have enough new format content
		# to test LLM summarization and prompts. Necessary until then.
		# https://github.com/rtCamp/rt-report-automation/issues
		self._old_parser = OldFormatParser()

	def _detect_format(self, message: dict) -> str:
		"""Detect which format a message uses.

		Args:
			message: Slack message object.

		Returns:
			"new" if message matches the new-format header,
			otherwise "old".

		"""
		return "new" if self._new_parser.is_new_format_message(message) else "old"

	def thread_has_new_format_identifier(self, messages: list[dict]) -> bool:
		"""Return True if any message in the thread has the new-format header."""
		for message in messages:
			if self._new_parser.is_new_format_message(message):
				return True
		return False

	@staticmethod
	def _keyword_anchor_for_line(line: str) -> str | None:
		"""Return a STANDARD_QUESTIONS key if the line is a keyword anchor.

		A line is treated as an anchor when it is short enough to be a question
		header (under 80 chars) and contains one of the KEYWORD_ANCHORS words.
		"""
		normalized = line.lower().strip()
		if not normalized or len(normalized) > 80:
			return None
		for question_key, keywords in KEYWORD_ANCHORS.items():
			if any(kw in normalized for kw in keywords):
				return question_key
		return None

	def parse_thread_legacy(
		self,
		messages: list[dict],
		thread_timestamp: float,
	) -> list[DailyUpdateEntry]:
		"""Parse an old-format thread using keyword anchors.

		Used when the thread belongs to a standup/tracker workflow but does not
		contain the new-format identifier.  Each reply is scanned for lines
		containing keyword anchors ("yesterday", "today", "blocker", "demo").
		Answer lines between anchors are grouped under the matching key.  Replies
		that contain no keyword anchors are skipped (treated as casual chat).

		Args:
			messages: List of Slack message objects from a thread.
			thread_timestamp: Timestamp of the thread parent message.

		Returns:
			List of DailyUpdateEntry with keyword-structured answers.

		"""
		first_message_is_bot = messages and (
			"bot_id" in messages[0] or messages[0].get("subtype") == "bot_message"
		)
		thread_replies = (
			messages[1:] if first_message_is_bot and len(messages) > 1 else messages
		)

		entries: list[DailyUpdateEntry] = []

		for message in thread_replies:
			text = self._new_parser.get_message_text(message).strip()
			if not text:
				continue

			answers: dict[str, list[str]] = {}
			current_key: str | None = None
			current_lines: list[str] = []

			for raw_line in text.splitlines():
				anchor = self._keyword_anchor_for_line(raw_line)
				if anchor:
					if current_key and current_lines:
						answers.setdefault(current_key, []).append(
							"\n".join(current_lines).strip()
						)
					current_key = anchor
					current_lines = []
				elif current_key:
					cleaned = raw_line.strip().lstrip("-• ").strip()
					if cleaned:
						current_lines.append(cleaned)

			# Commit last section.
			if current_key and current_lines:
				answers.setdefault(current_key, []).append(
					"\n".join(current_lines).strip()
				)

			# Skip replies that had no keyword anchors (casual chat).
			if not answers:
				continue

			message_ts = float(message.get("ts", thread_timestamp))
			message_date = datetime.fromtimestamp(message_ts, tz=UTC).strftime(
				"%B %d, %Y"
			)
			entry = DailyUpdateEntry(date=message_date, timestamp=message_ts)
			for question_key, answer_texts in answers.items():
				entry.answers[question_key] = [
					DailyUpdateQuestionAnswer(
						question_key=question_key, text=answer_text
					)
					for answer_text in answer_texts
					if answer_text
				]
			entries.append(entry)

		return entries

	def _get_parser_for_message(self, message: dict) -> BaseParser:
		"""Get appropriate parser for a message.

		Args:
			message: Slack message object.

		Returns:
			Parser instance (NewFormatParser or OldFormatParser).

		"""
		format_type = self._detect_format(message)
		return self._new_parser if format_type == "new" else self._old_parser

	def parse_thread(
		self,
		messages: list[dict],
		thread_timestamp: float,
	) -> list[DailyUpdateEntry]:
		"""Parse a Slack thread into structured standup data.

		Automatically detects format for each message and uses appropriate parser.

		Args:
			messages: List of Slack message objects from a thread.
			thread_timestamp: Timestamp of the thread parent message.

		Returns:
			List of parsed standup entries (one per message).

		"""
		first_message_is_bot = messages and (
			"bot_id" in messages[0] or messages[0].get("subtype") == "bot_message"
		)

		thread_replies = (
			messages[1:] if first_message_is_bot and len(messages) > 1 else messages
		)

		entries: list[DailyUpdateEntry] = []

		for message in thread_replies:
			has_text = "text" in message and message["text"].strip()
			has_blocks = "blocks" in message and message["blocks"]
			if not has_text and not has_blocks:
				continue

			parser = self._get_parser_for_message(message)

			if not parser.message_has_questions(message):
				continue

			message_text = parser.get_message_text(message)
			if not message_text.strip():
				continue

			parsed_answers = parser.parse_message_text(message_text)

			if not parsed_answers:
				continue

			message_ts = float(message.get("ts", thread_timestamp))
			message_date = datetime.fromtimestamp(
				message_ts,
				tz=UTC,
			).strftime("%B %d, %Y")

			entry = DailyUpdateEntry(
				date=message_date,
				timestamp=message_ts,
			)

			for question_key, answer_list in parsed_answers.items():
				for answer_text in answer_list:
					if answer_text:
						entry.answers.setdefault(question_key, []).append(
							DailyUpdateQuestionAnswer(
								question_key=question_key,
								text=answer_text,
							),
						)

			if entry.answers:
				entries.append(entry)

		return entries

	def _group_entries_by_date(
		self,
		entries: list[DailyUpdateEntry],
	) -> dict[str, list[DailyUpdateEntry]]:
		"""Group entries by date while preserving insertion order per date."""
		grouped: dict[str, list[DailyUpdateEntry]] = defaultdict(list)
		for entry in entries:
			grouped[entry.date].append(entry)
		return grouped

	def _collect_answer_texts(self, entry: DailyUpdateEntry) -> dict[str, list[str]]:
		"""Return normalized answer text lists for each standard question."""
		normalized_answers: dict[str, list[str]] = {}
		for question_key in STANDARD_QUESTIONS:
			answer_texts = [
				answer.text.strip()
				for answer in entry.answers.get(question_key, [])
				if answer.text.strip()
			]
			if answer_texts:
				normalized_answers[question_key] = answer_texts
		return normalized_answers

	def _format_entries_as_dict(
		self,
		entries: list[DailyUpdateEntry],
	) -> list[dict]:
		"""Format standup entries as dictionary structure grouped by date."""
		if not entries:
			return []

		entries_by_date = self._group_entries_by_date(entries)
		result = []

		for date_str in sorted(entries_by_date.keys()):
			standup_entries_list = []
			for entry in entries_by_date[date_str]:
				entry_payload = self._collect_answer_texts(entry)
				if entry_payload:
					standup_entries_list.append(entry_payload)

			if standup_entries_list:
				result.append(
					{
						"date": date_str,
						"standup_entries": standup_entries_list,
					},
				)

		return result

	def format_entries_as_toon(self, entries: list[DailyUpdateEntry]) -> str:
		"""Format standup entries as TOON format.

		Args:
			entries: List of parsed standup entries.

		Returns:
			TOON string with entries grouped by date.

		"""
		processed_entries = self._format_entries_as_dict(entries)
		return process_json_to_toon(processed_entries)
