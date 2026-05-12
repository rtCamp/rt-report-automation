"""Helper utilities for Google Docs integration."""

import logging
import re

from app.core.utils import log_and_raise
from app.google_docs.utils.constants import (
	MAX_DOC_ID_LENGTH,
	MAX_FOLDER_ID_LENGTH,
	MIN_DOC_ID_LENGTH,
	MIN_FOLDER_ID_LENGTH,
)

logger = logging.getLogger(__name__)

# Regex patterns for Google Drive folder ID extraction
# Matches: /folders/{folder_id} in URLs (captures folder ID)
# Example: "https://drive.google.com/drive/folders/abc123_xyz-456"
# -> captures "abc123_xyz-456"
# Pattern: /folders/([a-zA-Z0-9_-]{8,255})
#   - [a-zA-Z0-9_-] = alphanumeric characters, underscores, and hyphens
#   - {8,255} = length must be between MIN and MAX (bounded for security)
#   - () = capture group to extract the folder ID
FOLDER_URL_PATTERN = re.compile(
	rf"/folders/([a-zA-Z0-9_-]{{{MIN_FOLDER_ID_LENGTH},{MAX_FOLDER_ID_LENGTH}}})",
)

# Matches: Direct folder ID string (alphanumeric with - and _)
# Example: "abc123_xyz-456" -> matches entire string if valid
# Pattern: ^[a-zA-Z0-9_-]{8,255}$
#   - ^ = start of string
#   - [a-zA-Z0-9_-] = alphanumeric characters, underscores, and hyphens
#   - {8,255} = length must be between MIN and MAX (bounded for security)
#   - $ = end of string (ensures entire string matches, not just part)
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


# Regex patterns for Google Docs document ID extraction
# Matches: /document/d/{document_id} in URLs (captures document ID)
# Example: "https://docs.google.com/document/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/edit"
# -> captures "1aBcDeFgHiJkLmNoPqRsTuVwXyZ"
DOC_URL_PATTERN = re.compile(
	rf"/document/d/([a-zA-Z0-9_-]{{{MIN_DOC_ID_LENGTH},{MAX_DOC_ID_LENGTH}}})",
)


def extract_doc_id_from_url(doc_url: str) -> str:
	"""Extract document ID from a Google Docs URL.

	Supports various Google Docs URL formats:
	- https://docs.google.com/document/d/{doc_id}/edit
	- https://docs.google.com/document/d/{doc_id}

	Args:
		doc_url: Google Docs document URL.

	Returns:
		The extracted document ID.

	Raises:
		ValueError: If the URL format is invalid or document ID cannot be extracted.

	Examples:
		>>> extract_doc_id_from_url(
		...     "https://docs.google.com/document/d/1aBcDeFgHiJk/edit"
		... )
		'1aBcDeFgHiJk'

	"""
	if not doc_url or not doc_url.strip():
		log_and_raise(
			logger,
			"Document URL cannot be empty",
		)

	doc_url = doc_url.strip()

	match: re.Match[str] | None = DOC_URL_PATTERN.search(doc_url)
	if match:
		return match.group(1)

	return log_and_raise(
		logger,
		"Invalid Google Docs URL format",
	)


def fmt_hours(value: float) -> str:
	"""Format a hours value to a stable, human-friendly string.

	Rounds to 2 decimal places to eliminate floating-point artifacts
	(e.g. 0.30000000000000004), then strips trailing zeros so the result
	is compact: 6.50 -> "6.5", 35.00 -> "35".

	Args:
		value: A non-negative float representing hours.

	Returns:
		A clean decimal string.

	"""
	return f"{round(value, 2):g}"
