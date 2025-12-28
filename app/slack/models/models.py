"""Data models for Slack standup parsing."""

from dataclasses import dataclass, field


@dataclass
class StandupAnswer:
	"""Represents an answer to a standup question."""

	question_key: str
	text: str


@dataclass
class StandupEntry:
	"""Represents a parsed standup entry with questions and answers."""

	date: str
	timestamp: float
	answers: dict[str, list[StandupAnswer]] = field(default_factory=dict)
