"""Helper utilities for Google Docs integration."""

import logging
import re
from re import Match

from app.core.utils import log_and_raise
from app.google_docs.utils.constants import MIN_FOLDER_ID_LENGTH

logger = logging.getLogger(__name__)

# Regex patterns for Google Drive folder ID extraction
FOLDER_URL_PATTERN = re.compile(r"/folders/([a-zA-Z0-9_-]+)")
DIRECT_FOLDER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def extract_folder_id_from_drive_link(drive_link: str) -> str:
	"""Extract folder ID from a Google Drive folder link.

	Supports various Google Drive URL formats:
	- https://drive.google.com/drive/folders/{folder_id}
	- https://drive.google.com/drive/folders/{folder_id}?usp=sharing
	- https://drive.google.com/drive/u/0/folders/{folder_id}
	- Direct folder ID (if already extracted)

	Args:
		drive_link: Google Drive folder link or folder ID.

	Returns:
		The extracted folder ID.

	Raises:
		ValueError: If the link format is invalid or folder ID cannot be extracted.

	Examples:
		>>> extract_folder_id_from_drive_link(
		...     "https://drive.google.com/drive/folders/abc123xyz"
		... )
		'abc123xyz'
		>>> extract_folder_id_from_drive_link("abc123xyz456")
		'abc123xyz456'

	"""
	if not drive_link or not drive_link.strip():
		log_and_raise(
			logger,
			"Drive link cannot be empty",
		)

	drive_link = drive_link.strip()

	# Try to extract folder ID from URL pattern first
	match: Match[str] | None = FOLDER_URL_PATTERN.search(drive_link)
	if match:
		folder_id = match.group(1)
		# Validate extracted ID meets minimum length requirement
		if len(folder_id) < MIN_FOLDER_ID_LENGTH:
			log_and_raise(
				logger,
				f"Extracted folder ID '{folder_id}' is too short. "
				f"Minimum length: {MIN_FOLDER_ID_LENGTH}",
			)
		return folder_id

	# Check if it's already a direct folder ID (alphanumeric with - and _)
	is_direct_folder_id = (
		DIRECT_FOLDER_ID_PATTERN.match(drive_link)
		and len(drive_link) >= MIN_FOLDER_ID_LENGTH
	)

	if not is_direct_folder_id:
		log_and_raise(
			logger,
			f"Invalid Google Drive link format: '{drive_link}'. "
			f"Expected: Google Drive URL with /folders/{{folder_id}} "
			f"or direct folder ID (alphanumeric with - and _, "
			f"minimum {MIN_FOLDER_ID_LENGTH} characters).",
		)

	return drive_link
