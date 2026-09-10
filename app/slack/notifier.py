"""Service for sending direct messages to Slack users."""

import logging
from typing import cast

from slack_sdk import WebClient

from app.core.adapters.redis import redis_client
from app.core.config import settings
from app.core.utils import log_and_raise, validate
from app.slack.constants import (
	SLACK_USER_EMAIL_CACHE_KEY,
	SLACK_USER_EMAIL_CACHE_TTL,
)


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
		# Slack sends only the user ID, never the email, so this lookup is
		# unavoidable -- cached because the picker needs it per keystroke.
		cache_key = SLACK_USER_EMAIL_CACHE_KEY.format(user_id=user_id)
		try:
			cached = redis_client.get(cache_key)
			if cached:
				return cast("str", cached)
		except Exception as exc:
			self.logger.warning("Could not read cached email for %s: %s", user_id, exc)

		try:
			response = self.client.users_info(user=user_id)

			if not response["ok"]:
				self.logger.warning(f"Error looking up user info: {response['error']}")
				return None

			email = response.get("user", {}).get("profile", {}).get("email")

			if email:
				try:
					redis_client.set(
						cache_key,
						email,
						ex=SLACK_USER_EMAIL_CACHE_TTL,
					)
				except Exception as exc:
					self.logger.warning(
						"Could not cache email for %s: %s",
						user_id,
						exc,
					)

			return email

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

	def update_message(
		self,
		channel_id: str,
		ts: str,
		text: str,
		blocks: list[dict] | None = None,
	) -> bool:
		"""Replace an already-posted message in place.

		Lets an in-progress placeholder become the finished result in place.

		Args:
			channel_id (str): Channel the message lives in.
			ts (str): Timestamp identifying the message to update.
			text (str): New plain-text/mrkdwn fallback.
			blocks (list[dict] | None): New Block Kit blocks.

		Returns:
			bool: True if updated, False if Slack rejected it.

		"""
		validate(channel_id, str)
		validate(ts, str)
		validate(text, str)

		try:
			response = self.client.chat_update(
				channel=channel_id,
				ts=ts,
				text=text,
				blocks=blocks,
			)
		except Exception as exc:
			self.logger.warning(
				"Could not update message %s in %s: %s",
				ts,
				channel_id,
				exc,
			)
			return False

		if not response["ok"]:
			self.logger.warning(
				"Could not update message %s in %s: %s",
				ts,
				channel_id,
				response["error"],
			)
			return False

		return True

	def delete_message(self, channel_id: str, ts: str) -> bool:
		"""Remove a message the bot posted earlier.

		Clears an in-progress placeholder once the real result is posted.

		Args:
			channel_id (str): Channel the message lives in.
			ts (str): Timestamp identifying the message to delete.

		Returns:
			bool: True if deleted, False if Slack rejected it.

		"""
		validate(channel_id, str)
		validate(ts, str)

		try:
			response = self.client.chat_delete(channel=channel_id, ts=ts)
		except Exception as exc:
			# A leftover placeholder is untidy but must never fail delivery.
			self.logger.warning(
				"Could not delete message %s in %s: %s",
				ts,
				channel_id,
				exc,
			)
			return False

		if not response["ok"]:
			self.logger.warning(
				"Could not delete message %s in %s: %s",
				ts,
				channel_id,
				response["error"],
			)
			return False

		return True

	def post_to_channel(
		self,
		channel_id: str,
		text: str,
		blocks: list[dict] | None = None,
	) -> str | None:
		"""Post a visible message to a channel.

		The bot holds `chat:write` only, so this works in channels it has been
		invited to and fails elsewhere. Failure is expected, not exceptional:
		it returns None so the caller can fall back to `response_url`.

		Args:
			channel_id (str): Target channel ID, from the interaction payload.
			text (str): Plain-text/mrkdwn fallback message.
			blocks (list[dict] | None): Optional Block Kit blocks.

		Returns:
			str | None: The posted message's timestamp, which `update_message`
				needs to replace it later, or None if Slack rejected the post
				(e.g. the bot isn't in the channel).

		"""
		validate(channel_id, str)
		validate(text, str)

		try:
			response = self.client.chat_postMessage(
				channel=channel_id,
				text=text,
				blocks=blocks,
			)
		except Exception as exc:
			self.logger.warning(
				"Could not post to channel %s: %s",
				channel_id,
				exc,
			)
			return None

		if not response["ok"]:
			self.logger.warning(
				"Could not post to channel %s: %s",
				channel_id,
				response["error"],
			)
			return None

		return str(response["ts"])
