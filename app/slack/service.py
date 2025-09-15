"""Service for interacting with Slack API."""

import logging
from datetime import UTC, datetime

from slack_sdk import WebClient

from app.core.config import settings
from app.slack.constants import STANDUP_WORKFLOW_NAME


class SlackService:
	"""Service for interacting with Slack API."""

	def __init__(self):
		"""Initialize the SlackService."""
		self.client = WebClient(token=settings.SLACK_BOT_TOKEN.get_secret_value())
		self.logger = logging.getLogger(__name__)

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
		standups = ""
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
			standup_date = datetime.fromtimestamp(
				float(message["ts"]),
				tz=UTC,
			).strftime("%B %d, %Y at %I:%M %p UTC")

			# Add timestamp header
			standups += f"## {standup_date}\n\n"

			# Add each reply's text (skip first message - workflow trigger)
			for reply in replies[1:]:
				if "text" in reply and reply["text"].strip():
					standups += f"{reply['text']}\n\n"

		return standups
