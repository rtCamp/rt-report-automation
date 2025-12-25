"""Pydantic models for Google Docs API."""

from pydantic import BaseModel, Field, field_validator

from app.google_docs.utils.constants import MAX_REPLACEMENTS_ENTRIES


class GenerateDocRequest(BaseModel):
	"""Request model for generating a Google Doc.

	Attributes:
		replacements: Dictionary of template tag replacements.
			Keys should match the tags in your template (without delimiters).
			Values can be strings or lists of strings.
		doc_name: Optional custom name for the generated document.

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

	doc_name: str | None = Field(
		None,
		description="Optional name for the generated document",
		min_length=1,
		max_length=200,
		examples=["RT Report Automation Report - 2025-12-24"],
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
		if len(v) > MAX_REPLACEMENTS_ENTRIES:
			msg = (
				f"Replacements dictionary exceeds maximum allowed entries. "
				f"Maximum: {MAX_REPLACEMENTS_ENTRIES}, provided: {len(v)}"
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
