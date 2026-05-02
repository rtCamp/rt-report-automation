#!/usr/bin/env python3
"""POC script: replace {{{rtai-hoursBreakdown-rtai}}} with a real Google Docs table.

Usage (from repo root):
    python scripts/poc_hours_breakdown.py

The script directly modifies:
    https://docs.google.com/document/d/1z1lQxDdPZiua96DIfipBWbnxItP17ptGjtwxE5Isc7U/edit
"""

import os
import sys

# Add repo root to path so app imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.google_docs.services.google_auth import GoogleAuthService

# ─── Config ──────────────────────────────────────────────────────────────────

DOC_ID = "1z1lQxDdPZiua96DIfipBWbnxItP17ptGjtwxE5Isc7U"
PLACEHOLDER = "{{{rtai-hoursBreakdown-rtai}}}"
PLACEHOLDER_TOTAL_ESTIMATED = "{{{rtai-totalEstimateHours-rtai}}}"
PLACEHOLDER_TOTAL_CONSUMED = "{{{rtai-totalHoursConsumed-rtai}}}"

SAMPLE_HOURS_BREAKDOWN = [
	{"task_title": "Meetings", "estimated_hours": 8, "hours_consumed": 6.5},
	{"task_title": "Feature Development", "estimated_hours": 40, "hours_consumed": 35},
	{"task_title": "Code Review", "estimated_hours": 10, "hours_consumed": 12},
]

HEADERS = ["Task", "Estimated Hours", "Hours Consumed"]

# ─── Helpers ─────────────────────────────────────────────────────────────────


def find_placeholder(document: dict, placeholder: str) -> dict | None:
	"""Locate the placeholder in the document body or inside a table cell.

	Returns a dict with location info:
	  - body paragraph:  {"type": "paragraph", "start": int, "end": int}
	  - table cell:      {"type": "table_cell", "table_start": int,
	                      "row_idx": int, "col_idx": int}
	Returns None if not found.
	"""
	for element in document.get("body", {}).get("content", []):
		# ── Body paragraph ──
		para = element.get("paragraph")
		if para:
			for text_elem in para.get("elements", []):
				if placeholder in text_elem.get("textRun", {}).get("content", ""):
					return {
						"type": "paragraph",
						"start": element["startIndex"],
						"end": element["endIndex"],
					}

		# ── Table cell ──
		table = element.get("table")
		if table:
			for row_idx, row in enumerate(table.get("tableRows", [])):
				for col_idx, cell in enumerate(row.get("tableCells", [])):
					for cell_content in cell.get("content", []):
						cell_para = cell_content.get("paragraph")
						if not cell_para:
							continue
						for text_elem in cell_para.get("elements", []):
							if placeholder in text_elem.get("textRun", {}).get(
								"content", ""
							):
								return {
									"type": "table_cell",
									"table_start": element["startIndex"],
									"row_idx": row_idx,
									"col_idx": col_idx,
								}
	return None


def get_table_cells(document: dict, table_start: int) -> list[list[int]]:
	"""Return a 2D list of cell startIndexes for the table at table_start."""
	for element in document.get("body", {}).get("content", []):
		if "table" in element and element["startIndex"] == table_start:
			return [
				[cell["startIndex"] for cell in row.get("tableCells", [])]
				for row in element["table"].get("tableRows", [])
			]
	return []


def find_table_cells_near(document: dict, target_index: int) -> list[list[int]] | None:
	"""Find the table closest to target_index and return a 2D list of cell startIndexes."""
	best_table_element = None
	best_distance = float("inf")

	for element in document.get("body", {}).get("content", []):
		if "table" not in element:
			continue
		distance = abs(element.get("startIndex", 0) - target_index)
		if distance < best_distance:
			best_distance = distance
			best_table_element = element

	if best_table_element is None:
		return None

	return [
		[cell["startIndex"] for cell in row.get("tableCells", [])]
		for row in best_table_element["table"].get("tableRows", [])
	]


# ─── Main logic ──────────────────────────────────────────────────────────────


def _fill_and_bold(
	docs_service,
	doc_id: str,
	cells: list[list[int]],
	hours_breakdown: list[dict],
	header_row_idx: int,
) -> None:
	"""Fill cells and apply bold to header + totals rows.

	cells: full 2D cell index grid of the table (after all row insertions).
	header_row_idx: which row index holds the column headers (0 for new tables,
	                may differ for pre-existing tables if they already have headers).
	"""
	total_estimated = sum(item["estimated_hours"] for item in hours_breakdown)
	total_consumed = sum(item["hours_consumed"] for item in hours_breakdown)
	totals_values = [
		"TOTAL HOURS FOR PERIOD",
		str(total_estimated),
		str(total_consumed),
	]

	first_data_row = header_row_idx + 1
	totals_row_idx = first_data_row + len(hours_breakdown)

	# ── Fill cells (descending index order) ───────────────────────────────
	fill_ops: list[tuple[int, str]] = []

	# Header row (only written when we create the table; skipped for pre-existing)
	if header_row_idx == 0:
		for col, header in enumerate(HEADERS):
			fill_ops.append((cells[header_row_idx][col] + 1, header))

	# Data rows
	for i, item in enumerate(hours_breakdown):
		row_idx = first_data_row + i
		values = [
			str(item["task_title"]),
			str(item["estimated_hours"]),
			str(item["hours_consumed"]),
		]
		for col, val in enumerate(values):
			fill_ops.append((cells[row_idx][col] + 1, val))

	# Totals row
	for col, val in enumerate(totals_values):
		fill_ops.append((cells[totals_row_idx][col] + 1, val))

	fill_ops.sort(key=lambda x: x[0], reverse=True)

	print("Filling table cells…")
	docs_service.documents().batchUpdate(
		documentId=doc_id,
		body={
			"requests": [
				{"insertText": {"location": {"index": idx}, "text": text}}
				for idx, text in fill_ops
			]
		},
	).execute()

	# ── Bold: header row + totals row ────────────────────────────────────
	bold_requests = []

	for col, header in enumerate(HEADERS):
		start = cells[header_row_idx][col] + 1
		bold_requests.append(
			{
				"updateTextStyle": {
					"range": {"startIndex": start, "endIndex": start + len(header)},
					"textStyle": {"bold": True},
					"fields": "bold",
				}
			}
		)

	for col, val in enumerate(totals_values):
		start = cells[totals_row_idx][col] + 1
		bold_requests.append(
			{
				"updateTextStyle": {
					"range": {"startIndex": start, "endIndex": start + len(val)},
					"textStyle": {"bold": True},
					"fields": "bold",
				}
			}
		)

	print("Applying bold formatting…")
	docs_service.documents().batchUpdate(
		documentId=doc_id,
		body={"requests": bold_requests},
	).execute()


def insert_hours_breakdown_table(doc_id: str, hours_breakdown: list[dict]) -> None:
	auth = GoogleAuthService()
	docs_service = auth.get_docs_service()

	# ── Step 1: Fetch document, find placeholder ───────────────────────────
	print("Fetching document…")
	doc = docs_service.documents().get(documentId=doc_id).execute()

	location = find_placeholder(doc, PLACEHOLDER)
	if location is None:
		print(f"ERROR: placeholder '{PLACEHOLDER}' not found in document.")
		sys.exit(1)

	print(f"Placeholder found: {location}")

	# ── Step 2: Clear placeholder text ────────────────────────────────────
	print("Clearing placeholder text…")
	docs_service.documents().batchUpdate(
		documentId=doc_id,
		body={
			"requests": [
				{
					"replaceAllText": {
						"containsText": {"text": PLACEHOLDER, "matchCase": True},
						"replaceText": "",
					}
				}
			]
		},
	).execute()

	# ══════════════════════════════════════════════════════════════════════
	# CASE A: Placeholder was inside an existing table cell
	# Template structure:
	#   Row 0: Bold headers (Task | Estimated Hours | Hours Consumed)
	#   Row 1: Placeholder row (contains {{{rtai-hoursBreakdown-rtai}}})
	#   Row 2: Totals row (TOTAL HOURS FOR PERIOD | {{{rtai-totalEstimateHours-rtai}}} | ...)
	# Steps:
	#   1. Insert N task rows below placeholder row
	#   2. Fill task rows with data
	#   3. Delete the (now-empty) placeholder row
	#   4. Replace totals placeholders via replaceAllText
	# ══════════════════════════════════════════════════════════════════════
	if location["type"] == "table_cell":
		table_start = location["table_start"]
		placeholder_row = location["row_idx"]
		num_tasks = len(hours_breakdown)

		print(
			f"Existing table found. Inserting {num_tasks} task rows after row {placeholder_row}…"
		)

		# Insert N rows below the placeholder row (one per task)
		insert_row_requests = [
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
			for _ in range(num_tasks)
		]
		docs_service.documents().batchUpdate(
			documentId=doc_id,
			body={"requests": insert_row_requests},
		).execute()

		# Re-fetch to get updated cell positions
		print("Fetching updated document to read cell positions…")
		doc = docs_service.documents().get(documentId=doc_id).execute()
		cells = get_table_cells(doc, table_start)
		print(f"Table now has {len(cells)} rows × {len(cells[0])} cols")

		# Fill task rows (placeholder_row+1 … placeholder_row+N)
		fill_ops: list[tuple[int, str]] = []
		for i, item in enumerate(hours_breakdown):
			row_idx = placeholder_row + 1 + i
			values = [
				str(item["task_title"]),
				str(item["estimated_hours"]),
				str(item["hours_consumed"]),
			]
			for col, val in enumerate(values):
				fill_ops.append((cells[row_idx][col] + 1, val))

		fill_ops.sort(key=lambda x: x[0], reverse=True)

		# Build delete-row request. The placeholder row index is lower than all
		# the newly inserted rows, so sorting descending means fill ops execute
		# first (higher indices), then the delete — safe to batch together.
		delete_row_request = {
			"deleteTableRow": {
				"tableCellLocation": {
					"tableStartLocation": {"index": table_start},
					"rowIndex": placeholder_row,
					"columnIndex": 0,
				}
			}
		}

		# Compute totals
		total_estimated = sum(item["estimated_hours"] for item in hours_breakdown)
		total_consumed = sum(item["hours_consumed"] for item in hours_breakdown)

		print(
			"Filling task rows, deleting placeholder row, and replacing totals in one batch…"
		)
		docs_service.documents().batchUpdate(
			documentId=doc_id,
			body={
				"requests": [
					*(
						{"insertText": {"location": {"index": idx}, "text": text}}
						for idx, text in fill_ops
					),
					delete_row_request,
					{
						"replaceAllText": {
							"containsText": {
								"text": PLACEHOLDER_TOTAL_ESTIMATED,
								"matchCase": True,
							},
							"replaceText": str(total_estimated),
						}
					},
					{
						"replaceAllText": {
							"containsText": {
								"text": PLACEHOLDER_TOTAL_CONSUMED,
								"matchCase": True,
							},
							"replaceText": str(total_consumed),
						}
					},
				]
			},
		).execute()

	# ══════════════════════════════════════════════════════════════════════
	# CASE B: Placeholder was in a standalone body paragraph
	# → Create a brand-new table at that location
	# ══════════════════════════════════════════════════════════════════════
	else:
		para_start = location["start"]
		num_rows = len(hours_breakdown) + 2  # header + data + totals
		num_cols = len(HEADERS)

		print(
			f"No existing table. Inserting {num_rows}×{num_cols} table at index {para_start}…"
		)
		docs_service.documents().batchUpdate(
			documentId=doc_id,
			body={
				"requests": [
					{
						"insertTable": {
							"rows": num_rows,
							"columns": num_cols,
							"location": {"index": para_start},
						}
					}
				]
			},
		).execute()

		print("Fetching updated document to read cell positions…")
		doc = docs_service.documents().get(documentId=doc_id).execute()
		cells = find_table_cells_near(doc, para_start)
		if not cells:
			print("ERROR: could not locate the inserted table.")
			sys.exit(1)

		print(f"Table found: {len(cells)} rows × {len(cells[0])} cols")
		_fill_and_bold(docs_service, doc_id, cells, hours_breakdown, header_row_idx=0)

	print(f"\nDone! View the doc: https://docs.google.com/document/d/{doc_id}/edit")


if __name__ == "__main__":
	insert_hours_breakdown_table(DOC_ID, SAMPLE_HOURS_BREAKDOWN)
