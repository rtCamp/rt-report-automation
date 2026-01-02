"""Helper utilities for Google Docs integration."""

import logging
import re

from app.core.utils import log_and_raise
from app.google_docs.utils.constants import (
	MAX_FOLDER_ID_LENGTH,
	MIN_FOLDER_ID_LENGTH,
)

logger = logging.getLogger(__name__)

# Regex patterns for Google Drive folder ID extraction
FOLDER_URL_PATTERN = re.compile(
	rf"/folders/([a-zA-Z0-9_-]{{{MIN_FOLDER_ID_LENGTH},{MAX_FOLDER_ID_LENGTH}}})",
)
DIRECT_FOLDER_ID_PATTERN = re.compile(
	rf"^[a-zA-Z0-9_-]{{{MIN_FOLDER_ID_LENGTH},{MAX_FOLDER_ID_LENGTH}}}$",
)


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
	match: re.Match[str] | None = FOLDER_URL_PATTERN.search(drive_link)
	if match:
		return match.group(1)

	# Check if it's already a direct folder ID (alphanumeric with - and _)
	if not DIRECT_FOLDER_ID_PATTERN.match(drive_link):
		log_and_raise(
			logger,
			"Invalid Google Drive folder link format",
		)

	return drive_link
