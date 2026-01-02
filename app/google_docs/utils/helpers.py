"""Helper utilities for Google Docs integration."""

import logging
import re

from app.core.utils import log_and_raise

logger = logging.getLogger(__name__)


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

	"""
	if not drive_link or not drive_link.strip():
		log_and_raise(
			logger,
			"Drive link cannot be empty",
		)

	drive_link = drive_link.strip()

	# Pattern to match Google Drive folder URLs
	# Matches: /folders/{folder_id} or /folders/{folder_id}?...
	pattern = r"/folders/([a-zA-Z0-9_-]+)"
	match = re.search(pattern, drive_link)

	if match:
		return match.group(1)

	# If no match, check if it's already a folder ID (alphanumeric with - and _)
	if re.match(r"^[a-zA-Z0-9_-]+$", drive_link) and len(drive_link) > 10:
		return drive_link

	return log_and_raise(
		logger,
		f"Invalid Google Drive link format: {drive_link}. "
		"Expected format: https://drive.google.com/drive/folders/{{folder_id}}",
	)
