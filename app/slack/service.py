"""Service for interacting with Slack API."""

import logging

from slack_sdk import WebClient
from toon import encode as process_json_to_toon

from app.core.config import settings
from app.slack.constants import STANDUP_WORKFLOW_NAME
from app.slack.services.standup_parser.standup_parser import StandupParser


class SlackService:
	"""Service for interacting with Slack API."""

	def __init__(self):
		"""Initialize the SlackService."""
		self.client = WebClient(token=settings.SLACK_BOT_TOKEN.get_secret_value())
		self.logger = logging.getLogger(__name__)
		self.parser = StandupParser()

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
			raise
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
			raise
		return messages

	def _filter_messages_by_workflow(
		self,
		messages: list[dict],
		workflow_name: str,
	) -> list[dict]:
		"""Filter messages that are part of a specific workflow.

		Supports both old format ("AI Internal - Daily Tasks Tracker") and
		new format ("Daily Standup Tracker") workflows.

		Args:
			messages (list[dict]): The list of messages to filter.
			workflow_name (str): The name of the workflow to filter by.

		Returns:
			list[dict]: A list of messages that are part of the specified workflow.

		"""
		filtered_messages = []
		# New format uses "Daily Standup Tracker", old format uses workflow_name
		# Accept both to support migration period
		accepted_usernames = [
			workflow_name,  # Old format: "AI Internal - Daily Tasks Tracker"
			"Daily Standup Tracker",  # New format
		]

		for message in messages:
			if (
				"bot_id" in message
				and "username" in message
				and message["username"] in accepted_usernames
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
			raise
		return messages

	def get_standups(
		self,
		channel_name: str,
		start_time: int,
		end_time: int,
	) -> str:
		"""Fetch standup messages from a Slack channel and return as formatted text.

		Args:
			channel_name (str): The name of the Slack channel.
			start_time (int): The start time for fetching messages (Unix timestamp).
			end_time (int): The end time for fetching messages (Unix timestamp).

		Returns:
			str: Formatted text with standup messages grouped by date.

		"""
		channel_id = self._get_channel_id(channel_name)

		if not channel_id:
			error_msg = f"Channel not found: {channel_name}"
			self.logger.warning(error_msg)
			return ""

		# Fetch messages from the channel
		messages = self._get_messages(channel_id, start_time, end_time)

		# Filter messages by the standup workflow
		messages = self._filter_messages_by_workflow(
			messages,
			STANDUP_WORKFLOW_NAME,
		)

		all_standup_entries = []

		for message in messages:
			replies = self._get_thread_messages(channel_id, message["ts"])
			thread_timestamp = float(message["ts"])

			try:
				standup_entries = self.parser.parse_thread(replies, thread_timestamp)
				if standup_entries:
					all_standup_entries.extend(standup_entries)
				else:
					error_msg = (
						f"No structured questions found in thread {message['ts']}. "
						"Skipping."
					)
					self.logger.warning(error_msg)
			except Exception as e:
				error_msg = (
					f"Failed to parse standup thread {message['ts']}. "
					"Falling back to raw format."
				)
				self.logger.warning("%s: %s", error_msg, e)

		if all_standup_entries:
			return self.parser.format_entries_as_toon(all_standup_entries)

		return process_json_to_toon([])
