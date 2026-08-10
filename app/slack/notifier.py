"""Service for sending direct messages to Slack users."""

import logging

from slack_sdk import WebClient

from app.core.config import settings
from app.core.utils import log_and_raise, validate


class SlackNotifierService:
	"""Sends formatted Slack DMs to individual users via a dedicated bot app.

	Uses ``SLACK_PMS_CONNECTOR_BOT_TOKEN``, a separate bot token from the one
	used by ``SlackService`` for reading standup channels, so read and send
	permissions stay isolated.
	"""

	def __init__(self):
		"""Initialize the SlackNotifierService."""
		self.client = WebClient(
			token=settings.SLACK_PMS_CONNECTOR_BOT_TOKEN.get_secret_value(),
		)
		self.logger = logging.getLogger(__name__)

	def _get_user_id_by_email(self, email: str) -> str | None:
		"""Resolve a Slack user ID from an email address.

		Args:
			email (str): The user's email address.

		Returns:
			str | None: The Slack user ID, or None if no matching user exists
				in this workspace.

		"""
		try:
			response = self.client.users_lookupByEmail(email=email)

			if not response["ok"]:
				self.logger.warning(
					f"Error looking up user by email: {response['error']}",
				)
				return None

			return response.get("user", {}).get("id")

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while looking up user by email",
				exception_type=exc.__class__,
				cause=exc,
			)

	def get_user_email(self, user_id: str) -> str | None:
		"""Resolve a Slack user's email address from their user ID.

		Args:
			user_id (str): The Slack user ID.

		Returns:
			str | None: The user's email address, or None if it could not be
				resolved.

		"""
		try:
			response = self.client.users_info(user=user_id)

			if not response["ok"]:
				self.logger.warning(f"Error looking up user info: {response['error']}")
				return None

			return response.get("user", {}).get("profile", {}).get("email")

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while looking up user info",
				exception_type=exc.__class__,
				cause=exc,
			)

	def _open_dm_channel(self, user_id: str) -> str | None:
		"""Open (or reuse) a direct-message channel with a Slack user.

		Args:
			user_id (str): The Slack user ID.

		Returns:
			str | None: The DM channel ID, or None if it could not be opened.

		"""
		try:
			response = self.client.conversations_open(users=[user_id])

			if not response["ok"]:
				self.logger.warning(f"Error opening DM channel: {response['error']}")
				return None

			return response.get("channel", {}).get("id")

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while opening DM channel",
				exception_type=exc.__class__,
				cause=exc,
			)

	def send_message(
		self,
		email: str,
		text: str,
		blocks: list[dict] | None = None,
	) -> bool:
		"""Send a formatted Slack DM to a user identified by email.

		Args:
			email (str): The recipient's email address.
			text (str): Plain-text/mrkdwn fallback message.
			blocks (list[dict] | None): Optional Slack Block Kit blocks for
				richer formatting. When provided, Slack renders these instead
				of ``text``, which is still used as the notification preview.

		Returns:
			bool: True if the message was sent successfully, False if the
				user could not be resolved or the DM channel could not be
				opened.

		"""
		validate(email, str)
		validate(text, str)

		user_id = self._get_user_id_by_email(email)
		if not user_id:
			self.logger.warning(f"No Slack user found for email: {email}")
			return False

		channel_id = self._open_dm_channel(user_id)
		if not channel_id:
			self.logger.warning(f"Could not open DM channel for user: {user_id}")
			return False

		try:
			response = self.client.chat_postMessage(
				channel=channel_id,
				text=text,
				blocks=blocks,
			)

			if not response["ok"]:
				self.logger.error(f"Error sending message: {response['error']}")
				return False

			return True

		except Exception as exc:
			log_and_raise(
				self.logger,
				"Exception occurred while sending message",
				exception_type=exc.__class__,
				cause=exc,
			)
