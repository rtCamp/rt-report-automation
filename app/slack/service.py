import logging
import re
from datetime import UTC, datetime

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.core.config import settings
from app.slack.constants import STANDUP_WORKFLOW_NAME


class SlackService:
	"""Service for interacting with Slack API."""

	def __init__(self):
		"""Initialize the SlackService."""

		self.client = WebClient(token=settings.SLACK_BOT_TOKEN.get_secret_value())
		self.logger = logging.getLogger(__name__)

	def _validate_token(self) -> None:
		"""Validate the Slack bot token by making a test API call."""
		try:
			response = self.client.auth_test()
			if not response["ok"]:
				error = response.get("error", "Unknown error")
				raise ValueError(f"Invalid Slack bot token: {error}")
		except SlackApiError as e:
			raise ValueError(f"Slack API error: {e.response['error']}")
		except Exception as e:
			raise ValueError(f"Failed to validate Slack bot token: {str(e)}")

	def _get_channel_id(self, channel_name: str) -> str | None:
		"""Get the ID of a Slack channel by its name.

		Args:
			channel_name (str): The name of the Slack channel.

		Returns:
			str | None: The ID of the Slack channel, or None if not found.
		"""

		try:
			response = self.client.users_conversations()

			if not response["ok"]:
				self.logger.error(f"Error fetching channels: {response['error']}")
				return None

			channels = response.get("channels", [])

			for channel in channels:
				if channel["name"] == channel_name:
					return channel["id"]

		except Exception as e:
			self.logger.error(f"Exception occurred while fetching channels: {e}")
		return None

	def _get_messages(
		self,
		channel_id: str,
		start_time: int,
		end_time: int,
	) -> list[dict]:
		"""Get messages from a Slack channel within a specific time range.

		Args:
			channel_id (str): The ID of the Slack channel.
			start_time (int): The start time in Unix timestamp format.
			end_time (int): The end time in Unix timestamp format.

		Returns:
			list[dict]: A list of messages from the channel.
		"""

		messages = []
		cursor = None
		try:
			while True:
				response = self.client.conversations_history(
					channel=channel_id,
					oldest=str(start_time),
					latest=str(end_time),
					limit=1000,
					cursor=cursor,
				)

				if response["ok"]:
					messages.extend(response.get("messages", []))
					cursor = response.get("response_metadata", {}).get("next_cursor")

					if not cursor:
						break
				else:
					self.logger.error(f"Error fetching messages: {response['error']}")
					break

		except Exception as e:
			self.logger.error(f"Exception occurred while fetching messages: {e}")
		return messages

	def _filter_messages_by_workflow(
		self,
		messages: list[dict],
		workflow_name: str,
	) -> list[dict]:
		"""Filter messages that are part of a specific workflow.

		Args:
			messages (list[dict]): The list of messages to filter.
			workflow_name (str): The name of the workflow to filter by.

		Returns:
			list[dict]: A list of messages that are part of the specified workflow.
		"""

		filtered_messages = []
		for message in messages:
			if (
				"bot_id" in message
				and "username" in message
				and message["username"] == workflow_name
			):
				filtered_messages.append(message)

		return filtered_messages

	def _get_thread_messages(self, channel_id: str, thread_ts: str) -> list[dict]:
		"""Get all messages in a Slack thread.

		Args:
			channel_id (str): The ID of the Slack channel.
			thread_ts (str): The timestamp of the parent message of the thread.

		Returns:
			list[dict]: A list of messages in the thread.
		"""

		messages = []
		cursor = None
		try:
			while True:
				response = self.client.conversations_replies(
					channel=channel_id,
					ts=thread_ts,
					limit=1000,
					cursor=cursor,
				)

				if response["ok"]:
					messages.extend(response.get("messages", []))
					cursor = response.get("response_metadata", {}).get("next_cursor")

					if not cursor:
						break
				else:
					self.logger.error(
						f"Error fetching thread messages: {response['error']}",
					)
					break

		except Exception as e:
			self.logger.error(f"Exception occurred while fetching thread messages: {e}")
		return messages

	def _parse_standup_message(self, message: dict) -> dict | None:
		"""Parse a standup message and extract structured data.

		Args:
			message (dict): The Slack message containing standup text.

		Returns:
			dict: Parsed standup data with yesterday, today,
				blocker, and demo sections.
		"""
		try:
			standup_text = message.get("text", "")

			if not standup_text:
				self.logger.warning("Empty standup message text")
				return {
					"yesterday": [],
					"today": [],
					"blocker": [],
					"demo": [],
				}

			# Remove actual Unicode bullet characters (e.g., •, ‣, etc.)
			cleaned_text = re.sub(r"[\u2022\u2023\u25e6]", "", standup_text)

			# Extract sections using regex patterns
			# Yesterday section
			yesterday_pattern = (
				r"(What you worked on yesterday|What did you work on yesterday?)"
				r"[\s\S]*?(?:\n|:)([\s\S]*?)"
				r"(?=(What you are working on today|What are you working on today?))"
			)
			yesterday_match = re.search(yesterday_pattern, cleaned_text, re.IGNORECASE)

			# Today section
			today_pattern = (
				r"(What you are working on today|What are you working on today?)"
				r"[\s\S]*?(?:\n|:)([\s\S]*?)"
				r"(?=("
				r"Any blockers encountered of conversations needed|"
				r"Any blockers encountered or conversations needed?"
				r"))"
			)
			today_match = re.search(today_pattern, cleaned_text, re.IGNORECASE)

			# Blocker section
			blocker_pattern = (
				r"(Any blockers encountered of conversations needed|"
				r"Any blockers encountered or conversations needed?)"
				r"[\s\S]*?(?:\n|:)([\s\S]*?)"
				r"(?=(Anything you'd like to demo internally))"
			)
			blocker_match = re.search(blocker_pattern, cleaned_text, re.IGNORECASE)

			# Demo section
			demo_pattern = (
				r"(Anything you'd like to demo internally)"
				r"[\s\S]*?(?:\n|:)?([\s\S]*)$"
			)
			demo_match = re.search(demo_pattern, cleaned_text, re.IGNORECASE)

			def process_section(match_obj):
				"""Process matched section content into array."""
				if not match_obj or len(match_obj.groups()) < 2:
					return []

				content = match_obj.group(2) if match_obj.group(2) else ""
				# Remove bullet points and list markers
				content = re.sub(r"[*\-•◦▪▫]\s*", "", content)
				# Split by newlines and filter empty lines
				return [line.strip() for line in content.split("\n") if line.strip()]

			result = {
				"yesterday": process_section(yesterday_match),
				"today": process_section(today_match),
				"blocker": process_section(blocker_match),
				"demo": process_section(demo_match),
			}

			# Return None if no content found
			if not any(
				[
					result["yesterday"],
					result["today"],
					result["blocker"],
					result["demo"],
				],
			):
				return None

			return result

		except Exception as e:
			self.logger.warning(f"Failed to parse standup text: {e}")
			return {
				"yesterday": [],
				"today": [],
				"blocker": [],
				"demo": [],
			}

	def _parse_standup_messages(self, messages: list[dict]) -> list[dict]:
		"""Parse multiple standup messages.

		Args:
			messages (list[dict]): A list of Slack messages containing standup text.

		Returns:
			list[dict]: A list of parsed standup data.
		"""
		parsed_standups = []

		for message in messages:
			parsed = self._parse_standup_message(message)

			if parsed is not None:
				parsed_standups.append(parsed)
		return parsed_standups

	def get_standups(
		self,
		channel_name: str,
		start_time: int,
		end_time: int,
	) -> dict[str, list[dict]]:
		"""Fetch and parse standup messages from a Slack channel.

		Args:
			channel_name (str): The name of the Slack channel.
			start_time (int): The start time for fetching messages (Unix timestamp).
			end_time (int): The end time for fetching messages (Unix timestamp).

		Returns:
			dict[str, list[dict]]: A dictionary where keys are ISO timestamp strings
				and values are lists of parsed standup dictionaries. Each standup dict
				contains 'yesterday', 'today', 'blocker', 'demo', and 'text' keys.
		"""
		self._validate_token()

		standups = {}
		channel_id = self._get_channel_id(channel_name)

		if not channel_id:
			self.logger.warning(f"Channel not found: {channel_name}")
			return standups

		# Fetch messages from the channel
		messages = self._get_messages(channel_id, start_time, end_time)

		# Filter messages by the standup workflow
		messages = self._filter_messages_by_workflow(
			messages,
			STANDUP_WORKFLOW_NAME,
		)

		for message in messages:
			replies = self._get_thread_messages(channel_id, message["ts"])
			parsed_replies = self._parse_standup_messages(replies[1:])
			iso_timestamp = datetime.fromtimestamp(
				float(message["ts"]),
				tz=UTC,
			).isoformat()
			standups[iso_timestamp] = parsed_replies

		return standups
