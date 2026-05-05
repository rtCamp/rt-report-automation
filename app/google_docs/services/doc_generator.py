"""Document generation service for Google Docs."""

import logging
import re
from typing import Any

from app.core.config import settings
from app.core.utils import log_and_raise
from app.google_docs.services.converters import build_replacement_requests
from app.google_docs.services.folder_manager import FolderManagerService
from app.google_docs.services.google_auth import GoogleAuthService
from app.google_docs.utils.constants import get_template_tag
from app.llm.models.summarization import HoursBreakdownItem

# Keys whose LLM output is already markdown (bold, italic, bullet lists, etc.).
_MARKDOWN_KEYS: frozenset[str] = frozenset({"summary", "riskBlockerActionNeeded"})

# Keys whose LLM output uses tab-indented format that must be converted to
# markdown bullets before insertion.
_TASK_KEYS: frozenset[str] = frozenset({"completed", "inProgress", "inReview"})

logger = logging.getLogger(__name__)


def _task_section_to_md(raw: str) -> str:
	"""Convert tab-indented task text produced by the LLM into markdown bullets.

	The LLM outputs task sections as a title line followed by tab-indented
	sub-items.  This function converts each line to a ``- `` prefixed markdown
	list item at the appropriate indent depth (4 spaces per tab level).

	Args:
		raw: Tab-indented task string from the LLM.

	Returns:
		Markdown bullet-list string suitable for ``_build_markdown_insert_requests``.

	"""
	lines = []
	for line in raw.strip().split("\n"):
		if not line.strip():
			continue
		stripped = line.lstrip("\t")
		depth = len(line) - len(stripped)
		text = stripped.strip()
		if text:
			lines.append("    " * depth + "- " + text)
	return "\n".join(lines)


def _find_placeholders(docs_service: Any, document_id: str) -> dict[str, dict]:
	"""Return the start/end indices of every placeholder tag in the document.

	Scans all text runs in the document body and records the absolute start
	and end index of each tag that matches ``{{{rtai-...-rtai}}}`` or
	``{{...}}``.

	Args:
		docs_service: Authenticated Google Docs API service object.
		document_id: ID of the document to scan.

	Returns:
		``{{{rtai-key-rtai}}}: {"start_index": int, "end_index": int}``.

	"""
	doc = docs_service.documents().get(documentId=document_id).execute()
	body_content = doc.get("body", {}).get("content", [])
	placeholder_pattern = re.compile(r"\{\{\{[^{}]+\}\}\}|\{\{[^{}]+\}\}")
	placeholders: dict[str, dict] = {}

	for element in body_content:
		paragraph = element.get("paragraph")
		if not paragraph:
			continue
		for elem in paragraph.get("elements", []):
			text_run = elem.get("textRun")
			if not text_run:
				continue
			text = text_run.get("content", "")
			elem_start = elem.get("startIndex", 0)
			for match in placeholder_pattern.finditer(text):
				tag = match.group(0)
				placeholders[tag] = {
					"start_index": elem_start + match.start(),
					"end_index": elem_start + match.end(),
				}

	return placeholders


def _build_typed_replacements(
	replacements: dict[str, str | list[str]],
) -> dict[str, dict]:
	"""Convert the flat replacements dict to the typed descriptor format.

	Plain text keys stay as ``{"type": "text", "value": "..."}``.
	Markdown keys (summary, riskBlockerActionNeeded) become
	``{"type": "markdown", ...}``.
	Task keys (completed, inProgress, inReview) are converted from
	tab-indented format to markdown bullets first.

	The dict is keyed by the rendered template tag, e.g.
	``"{{{rtai-projectName-rtai}}}"``.

	Args:
		replacements: Raw replacements dict from the request or Inngest event.

	Returns:
		Tag-keyed typed replacement descriptor dict.

	"""
	typed: dict[str, dict] = {}

	for key, value in replacements.items():
		# Normalise list values to a newline-joined string.
		text_value = "\n".join(value) if isinstance(value, list) else value
		tag = get_template_tag(key)  # e.g. "{{{rtai-projectName-rtai}}}"

		if key in _TASK_KEYS:
			typed[tag] = {
				"type": "markdown",
				"value": _task_section_to_md(text_value),
			}
		elif key in _MARKDOWN_KEYS:
			typed[tag] = {"type": "markdown", "value": text_value}
		else:
			typed[tag] = {"type": "text", "value": text_value}

	return typed


class DocGeneratorService:
	"""Service for generating Google Docs from templates."""

	def __init__(self):
		"""Initialize the DocGeneratorService."""
		self.auth_service = GoogleAuthService()
		self.folder_manager = FolderManagerService()

	async def create_doc_from_template(
		self,
		replacements: dict[str, str | list[str]],
		output_name: str,
		parent_folder_id: str,
		hours_breakdown: list[HoursBreakdownItem] | None = None,
	) -> str:
		"""Create a Google Doc from a template with replacements.

		Args:
			replacements: Dictionary of key-value pairs for template replacements.
			output_name: Name for the generated document.
			parent_folder_id: Google Drive parent folder ID. The 'Automated Docs'
				folder must already exist within this parent.
			hours_breakdown: Optional list of task hours entries. When provided,
				the placeholder row in the template table is replaced with one
				row per task and a totals row.

		Returns:
			str: URL of the created document.

		Raises:
			ValueError: If output_name is empty, parent_folder_id is empty,
				replacement keys are empty, or template tag keys contain
				invalid characters.
			Exception: If document creation or update fails.

		"""
		# Validate inputs
		if not parent_folder_id:
			log_and_raise(
				logger,
				"parent_folder_id is required and cannot be empty",
			)

		# Validate replacement keys
		for key in replacements:
			if not key or not key.strip():
				log_and_raise(
					logger,
					"Replacement keys cannot be empty",
				)

		# Each call creates a NEW service object with its own httplib2.Http() instance.
		# This ensures thread-safety - even if multiple threads call this method
		# simultaneously, each gets its own service objects.
		drive_service: Any = self.auth_service.get_drive_service()
		docs_service: Any = self.auth_service.get_docs_service()

		# Step 1: Copy the template document
		copy_request_body: dict[str, str | list[str]] = {
			"name": output_name.strip(),
		}

		# Find the automated docs folder within the provided parent folder
		automated_folder_id = await self.folder_manager.get_automated_docs_folder(
			parent_folder_id,
		)
		copy_request_body["parents"] = [automated_folder_id]

		try:
			copied_file = (
				drive_service.files()
				.copy(
					fileId=settings.GOOGLE_TEMPLATE_DOC_ID,
					body=copy_request_body,
					supportsAllDrives=True,
				)
				.execute()
			)
		except Exception as e:
			log_and_raise(
				logger,
				"Failed to copy template document. Check folder permissions.",
				Exception,
				e,
			)

		doc_id = copied_file.get("id")

		if not doc_id or not isinstance(doc_id, str):
			log_and_raise(
				logger,
				"Failed to create document copy - no document ID returned",
			)

		# Step 2: Locate placeholder tags in the copied document
		placeholders = _find_placeholders(docs_service, doc_id)

		# Step 3: Build typed replacement descriptors (text vs markdown)
		typed_replacements = _build_typed_replacements(replacements)

		# Only apply replacements for tags that actually exist in this template
		applicable = {
			tag: repl for tag, repl in typed_replacements.items() if tag in placeholders
		}

		# Step 4: Build and execute a single batchUpdate with rich formatting
		requests = build_replacement_requests(placeholders, applicable)

		if requests:
			try:
				docs_service.documents().batchUpdate(
					documentId=doc_id,
					body={"requests": requests},
				).execute()
			except Exception as e:
				log_and_raise(
					logger,
					"Failed to update document with replacements. Check template tags.",
					Exception,
					e,
				)

		# Step 4: Insert hours breakdown table rows (if provided)
		if hours_breakdown:
			self._insert_hours_breakdown(docs_service, doc_id, hours_breakdown)

		# Return the document URL
		return f"https://docs.google.com/document/d/{doc_id}/edit"

	def _insert_hours_breakdown(
		self,
		docs_service: Any,
		doc_id: str,
		hours_breakdown: list[HoursBreakdownItem],
	) -> None:
		"""Insert task rows into the hours breakdown table in the document.

		Expects the template to contain a 2-column table with:
			- Row 0: Bold column headers (pre-built in template)
			- Row 1: A cell containing {{{rtai-hoursBreakdown-rtai}}}
			- Row 2: Totals row with {{{rtai-totalHoursConsumed-rtai}}}

		Steps:
			1. Fetch the doc to find the placeholder cell location
			2. Clear placeholder text
			3. Insert N task rows below the placeholder row
			4. Re-fetch to get fresh cell indices
			5. Fill task rows + delete placeholder row + replace totals (single batch)

		Args:
			docs_service: Authenticated Google Docs API service.
			doc_id: The document ID to update.
			hours_breakdown: List of task hours entries.

		Raises:
			Exception: If any API call fails or the placeholder is not found.

		"""
		# Fetch document to locate placeholder
		try:
			doc = docs_service.documents().get(documentId=doc_id).execute()
		except Exception as e:
			log_and_raise(
				logger, "Failed to fetch document for hours breakdown", Exception, e
			)

		location = self._find_placeholder_in_table(
			doc, get_template_tag("hoursBreakdown")
		)
		if location is None:
			logger.warning(
				"Hours breakdown placeholder not found in document %s — skipping.",
				doc_id,
			)
			return

		table_start: int = location["table_start"]
		placeholder_row: int = location["row_idx"]

		# Clear placeholder text
		try:
			docs_service.documents().batchUpdate(
				documentId=doc_id,
				body={
					"requests": [
						{
							"replaceAllText": {
								"containsText": {
									"text": get_template_tag("hoursBreakdown"),
									"matchCase": True,
								},
								"replaceText": "",
							}
						}
					]
				},
			).execute()
		except Exception as e:
			log_and_raise(
				logger, "Failed to clear hours breakdown placeholder", Exception, e
			)

		# Insert one row per task below the placeholder row
		try:
			docs_service.documents().batchUpdate(
				documentId=doc_id,
				body={
					"requests": [
						{
							"insertTableRow": {
								"tableCellLocation": {
									"tableStartLocation": {"index": table_start},
									"rowIndex": placeholder_row,
									"columnIndex": 0,
								},
								"insertBelow": True,
							}
						}
						for _ in hours_breakdown
					]
				},
			).execute()
		except Exception as e:
			log_and_raise(logger, "Failed to insert hours breakdown rows", Exception, e)

		# Re-fetch to get updated cell positions
		try:
			doc = docs_service.documents().get(documentId=doc_id).execute()
		except Exception as e:
			log_and_raise(
				logger, "Failed to re-fetch document after row insertion", Exception, e
			)

		cells = self._get_table_cells(doc, table_start)

		# Build fill ops (task rows only, descending index order)
		fill_ops: list[tuple[int, str]] = []
		for i, item in enumerate(hours_breakdown):
			row_idx = placeholder_row + 1 + i
			for col, val in enumerate(
				[
					item.task_title,
					str(item.hours_consumed),
				]
			):
				fill_ops.append((cells[row_idx][col] + 1, val))

		fill_ops.sort(key=lambda x: x[0], reverse=True)

		total_consumed = sum(item.hours_consumed for item in hours_breakdown)

		# Single batch: fill task rows + delete placeholder row + replace totals
		try:
			docs_service.documents().batchUpdate(
				documentId=doc_id,
				body={
					"requests": [
						*(
							{"insertText": {"location": {"index": idx}, "text": text}}
							for idx, text in fill_ops
						),
						{
							"deleteTableRow": {
								"tableCellLocation": {
									"tableStartLocation": {"index": table_start},
									"rowIndex": placeholder_row,
									"columnIndex": 0,
								}
							}
						},
						{
							"replaceAllText": {
								"containsText": {
									"text": get_template_tag("totalHoursConsumed"),
									"matchCase": True,
								},
								"replaceText": str(total_consumed),
							}
						},
					]
				},
			).execute()
		except Exception as e:
			log_and_raise(
				logger, "Failed to populate hours breakdown table", Exception, e
			)

	@staticmethod
	def _find_placeholder_in_table(document: dict, placeholder: str) -> dict | None:
		"""Find a placeholder string inside a table cell.

		Returns a dict with ``table_start`` and ``row_idx`` / ``col_idx``,
		or None if not found.
		"""
		for element in document.get("body", {}).get("content", []):
			table = element.get("table")
			if not table:
				continue
			for row_idx, row in enumerate(table.get("tableRows", [])):
				for col_idx, cell in enumerate(row.get("tableCells", [])):
					for cell_content in cell.get("content", []):
						para = cell_content.get("paragraph")
						if not para:
							continue
						for text_elem in para.get("elements", []):
							if placeholder in text_elem.get("textRun", {}).get(
								"content", ""
							):
								return {
									"table_start": element["startIndex"],
									"row_idx": row_idx,
									"col_idx": col_idx,
								}
		return None

	@staticmethod
	def _get_table_cells(document: dict, table_start: int) -> list[list[int]]:
		"""Return a 2D list of cell startIndexes for the table at table_start."""
		for element in document.get("body", {}).get("content", []):
			if "table" in element and element["startIndex"] == table_start:
				return [
					[cell["startIndex"] for cell in row.get("tableCells", [])]
					for row in element["table"].get("tableRows", [])
				]
		return []
