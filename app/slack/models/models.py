"""Data models for Slack standup parsing."""

from dataclasses import dataclass, field


@dataclass
class DailyUpdateQuestionAnswer:
	"""Represents an answer captured for a single question."""

	question_key: str
	text: str


@dataclass
class DailyUpdateEntry:
	"""Represents a parsed update entry with questions and answers."""

	date: str
	timestamp: float
	answers: dict[str, list[DailyUpdateQuestionAnswer]] = field(default_factory=dict)
