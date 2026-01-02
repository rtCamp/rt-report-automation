"""Pydantic models for Google Docs API."""

from pydantic import BaseModel, Field, field_validator

from app.google_docs.utils.constants import (
	MAX_REPLACEMENT_ENTRIES,
	MIN_FOLDER_ID_LENGTH,
)


class GenerateDocRequest(BaseModel):
	"""Request model for generating a Google Doc.

	Attributes:
		replacements: Dictionary of template tag replacements.
			Keys should match the tags in your template (without delimiters).
			Values can be strings or lists of strings.
		doc_name: Name for the generated document.
		parent_folder_id: Google Drive parent folder ID. The 'Automated Docs'
			folder must already exist within this parent.

	"""

	replacements: dict[str, str | list[str]] = Field(
		...,
		description="Dictionary of template tag replacements",
		examples=[
			{
				"projectName": "RT Report Automation",
				"from": "December 1, 2025",
				"to": "December 24, 2025",
				"name": "Nam Dong",
				"projectStatus": "Green",
				"summary": "Project summary text",
				"riskBlockerActionNeeded": "No blockers",
				"completed": "Task 1\nTask 2",
				"inProgress": "Task 3",
				"inReview": "Task 4",
			},
		],
	)

	doc_name: str = Field(
		...,
		description="Name for the generated document.",
		min_length=1,
		max_length=200,
		examples=["RT Report Automation - 1st Dec 2025 - 24th Dec 2025"],
	)

	parent_folder_id: str = Field(
		...,
		description=(
			"Google Drive parent folder ID (extracted from drive_link). "
			"The 'Automated Docs' folder must exist within this parent."
		),
		min_length=MIN_FOLDER_ID_LENGTH,
		examples=["1a2b3c4d5e6f7g8h9i0j"],
	)

	@field_validator("replacements")
	@classmethod
	def validate_replacements(
		cls,
		v: dict[str, str | list[str]],
	) -> dict[str, str | list[str]]:
		"""Validate replacements dictionary size.

		Args:
			v: The replacements dictionary to validate.

		Returns:
			The validated replacements dictionary.

		Raises:
			ValueError: If the dictionary exceeds maximum allowed entries.

		"""
		if len(v) > MAX_REPLACEMENT_ENTRIES:
			msg = (
				f"Replacements dictionary exceeds maximum allowed entries. "
				f"Maximum: {MAX_REPLACEMENT_ENTRIES}, provided: {len(v)}"
			)
			raise ValueError(msg)

		return v


class GenerateDocResponse(BaseModel):
	"""Response model for document generation.

	Attributes:
		document_url: The URL of the generated Google Doc.

	"""

	document_url: str = Field(
		...,
		description="URL of the generated Google Doc",
		examples=["https://docs.google.com/document/d/1234567890abcdef/edit"],
	)
