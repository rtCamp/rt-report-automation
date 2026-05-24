"""Markdown parser and Google Docs API request builder for placeholder replacement.

Converts markdown text into a sequence of Google Docs batchUpdate requests
that insert styled text (bold, italic, bullets, headings, etc.) at a given index.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from markdown_it import MarkdownIt


@dataclass
class StyledRun:
	"""A contiguous run of text with inline styling."""

	text: str
	bold: bool = False
	italic: bool = False


@dataclass
class DocBlock:
	"""A paragraph-level block: heading, paragraph, list item etc."""

	runs: list[StyledRun] = field(default_factory=list)
	heading_level: int | None = None
	bullet: bool = False
	ordered: bool = False
	list_level: int = 0


def markdown_to_blocks(md_text: str) -> list[DocBlock]:
	"""Parse markdown into a list of DocBlocks using markdown-it-py.

	Args:
		md_text: Markdown-formatted string.

	Returns:
		Ordered list of DocBlock objects representing the parsed content.

	"""
	md = MarkdownIt("commonmark", {"typographer": False})
	tokens = md.parse(md_text)
	blocks: list[DocBlock] = []
	_walk_tokens(tokens, blocks)
	return blocks


def _walk_list(tokens: list, start: int, level: int, blocks: list[DocBlock]) -> int:
	"""Walk a (possibly nested) list starting at the list_open token.

	Args:
		tokens: Full token list from markdown-it.
		start: Index of the list_open token.
		level: Current nesting depth (0 = top level).
		blocks: Output list to append DocBlocks to.

	Returns:
		Index immediately after the corresponding list_close token.

	"""
	open_tok = tokens[start]
	is_bullet = open_tok.type == "bullet_list_open"
	close_type = "bullet_list_close" if is_bullet else "ordered_list_close"

	i = start + 1  # skip the list_open token
	while i < len(tokens) and tokens[i].type != close_type:
		tok = tokens[i]
		if tok.type == "list_item_open":
			i += 1
			while i < len(tokens) and tokens[i].type != "list_item_close":
				if tokens[i].type == "paragraph_open":
					inline_tok = tokens[i + 1]
					runs = _inline_to_runs(inline_tok.children or [])
					blocks.append(
						DocBlock(
							runs=runs,
							bullet=is_bullet,
							ordered=not is_bullet,
							list_level=level,
						),
					)
					i += 3  # paragraph_open, inline, paragraph_close
				elif tokens[i].type in ("bullet_list_open", "ordered_list_open"):
					i = _walk_list(tokens, i, level + 1, blocks)
				else:
					i += 1
		elif tok.type == "list_item_close":
			i += 1
		else:
			i += 1

	return i + 1  # skip the list_close token


def _walk_tokens(tokens: list, blocks: list[DocBlock]) -> None:
	"""Iterate over top-level token pairs and convert them to DocBlocks.

	Args:
		tokens: Top-level token list from markdown-it.
		blocks: Output list to append DocBlocks to.

	"""
	i = 0
	while i < len(tokens):
		tok = tokens[i]

		if tok.type == "heading_open":
			level = int(tok.tag[1])  # h1 → 1, h2 → 2, etc.
			inline_tok = tokens[i + 1]
			runs = _inline_to_runs(inline_tok.children or [])
			blocks.append(DocBlock(runs=runs, heading_level=level))
			i += 3  # heading_open, inline, heading_close
			continue

		if tok.type == "paragraph_open":
			inline_tok = tokens[i + 1]
			runs = _inline_to_runs(inline_tok.children or [])
			blocks.append(DocBlock(runs=runs))
			i += 3
			continue

		if tok.type in ("bullet_list_open", "ordered_list_open"):
			i = _walk_list(tokens, i, 0, blocks)
			continue

		i += 1  # skip unrecognised tokens


def _inline_to_runs(children: list) -> list[StyledRun]:
	"""Convert markdown-it inline children to a list of StyledRuns.

	Args:
		children: Inline token children from a markdown-it token.

	Returns:
		List of StyledRun objects representing the inline content.

	"""
	runs: list[StyledRun] = []
	bold = False
	italic = False

	for child in children:
		if child.type == "text":
			runs.append(
				StyledRun(
					text=child.content,
					bold=bold,
					italic=italic,
				),
			)
		elif child.type == "softbreak":
			runs.append(StyledRun(text="\n"))
		elif child.type == "strong_open":
			bold = True
		elif child.type == "strong_close":
			bold = False
		elif child.type == "em_open":
			italic = True
		elif child.type == "em_close":
			italic = False

	return runs or [StyledRun(text="")]


def build_replacement_requests(
	placeholders: dict[str, dict],
	replacements: dict,
) -> list[dict]:
	"""Build batchUpdate requests to replace placeholder tags with content.

	Processes placeholders in reverse index order so earlier-position insertions
	do not shift the indices of later ones.

	Args:
		placeholders: Mapping of tag string → {"start_index": int, "end_index": int},
			as returned by find_placeholders().
		replacements: Mapping of tag string → replacement descriptor.
			Each descriptor is a dict with at minimum a ``"type"`` key:
			``{"type": "text", "value": "..."}`` for plain text insertion or
			``{"type": "markdown", "value": "..."}`` for markdown with styling.

	Returns:
		List of Google Docs batchUpdate request dicts, ready to be passed in
		``body={"requests": ...}``.

	"""
	requests: list[dict] = []

	sorted_tags = sorted(
		[(tag, info) for tag, info in placeholders.items() if tag in replacements],
		key=lambda x: x[1]["start_index"],
		reverse=True,
	)

	for tag, pos in sorted_tags:
		replacement = replacements[tag]
		start = pos["start_index"]
		end = pos["end_index"]

		requests.append(
			{"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}},
		)

		rtype = replacement.get("type", "text")
		value = replacement.get("value", "")

		if rtype == "markdown":
			requests.extend(_build_markdown_insert_requests(value, start))
		else:
			requests.append(
				{"insertText": {"location": {"index": start}, "text": value}},
			)
			# Apply color if provided
			color = replacement.get("color")
			if color:
				requests.append(
					{
						"updateTextStyle": {
							"range": {
								"startIndex": start,
								"endIndex": start + len(value),
							},
							"textStyle": {
								"backgroundColor": {
									"color": {"rgbColor": color},
								},
								"bold": True,  # Making it bold for better visibility
							},
							"fields": "backgroundColor,bold",
						},
					},
				)

	return requests


def _build_markdown_insert_requests(md_text: str, start_index: int) -> list[dict]:
	"""Insert markdown content at *start_index* with full Google Docs styling.

	Blocks are iterated in reverse order so each one is inserted at the same
	``start_index`` without shifting the indices of subsequent insertions.

	For each block the request sequence is:
	1. ``insertText``
	2. ``updateTextStyle`` (bold, italic, etc.)
	3. ``updateParagraphStyle`` (heading named style)
	4. ``createParagraphBullets`` (bullet / ordered list)

	Args:
		md_text: Markdown-formatted string to insert.
		start_index: Document index at which to insert the content.

	Returns:
		List of Google Docs batchUpdate request dicts.

	"""
	if not md_text:
		return []

	blocks = markdown_to_blocks(md_text)
	if not blocks:
		return []

	requests: list[dict] = []

	def _emit_run_styles(
		blk: DocBlock,
		rs: int,
		*,
		force_bold: bool | None = None,
	) -> list[dict]:
		"""Return updateTextStyle requests for all styled runs in *blk*.

		Args:
			blk: DocBlock whose runs to process.
			rs: Absolute start index of the first run.
			force_bold: If provided, overrides the run's own bold flag.
				Used to bold top-level list items and un-bold sub-items.

		Returns:
			List of updateTextStyle request dicts.

		"""
		reqs: list[dict] = []
		for run in blk.runs:
			re = rs + len(run.text)
			if re > rs:
				# Always include bold and italic so that runs with no explicit
				# styling explicitly clear any bold/italic inherited from the
				# surrounding template paragraph.
				bold = force_bold if force_bold is not None else run.bold
				style: dict = {"bold": bold, "italic": run.italic}
				fields: list[str] = ["bold", "italic"]
				reqs.append(
					{
						"updateTextStyle": {
							"range": {"startIndex": rs, "endIndex": re},
							"textStyle": style,
							"fields": ",".join(fields),
						},
					},
				)
			rs = re
		return reqs

	i = len(blocks) - 1
	while i >= 0:
		block = blocks[i]

		# ── List items (bullet or ordered) ───────────────────────────────────
		# Group ALL consecutive list blocks and insert them as one string so
		# the API receives clean paragraph boundaries.  A single
		# createParagraphBullets call is then issued for the whole group.
		if block.bullet or block.ordered:
			grp_end = i
			grp_start = i
			while grp_start > 0 and (
				blocks[grp_start - 1].bullet or blocks[grp_start - 1].ordered
			):
				grp_start -= 1

			group = blocks[grp_start : grp_end + 1]
			is_bullet = group[0].bullet

			# Build full text: "\t" * level + run_text + "\n" per item.
			# The last item omits the trailing "\n" to avoid creating an empty
			# paragraph that the API would turn into a stray bullet point.
			parts: list[str] = []
			for idx, grp_block in enumerate(group):
				tab_prefix = "\t" * grp_block.list_level
				line = tab_prefix + "".join(r.text for r in grp_block.runs)
				if idx < len(group) - 1:
					line += "\n"
				parts.append(line)
			full_text = "".join(parts)

			requests.append(
				{
					"insertText": {
						"location": {"index": start_index},
						"text": full_text,
					},
				},
			)

			# Absolute run-style requests.
			# Top-level items (list_level 0) → bold, sub-items → plain text.
			char_pos = start_index
			for grp_block in group:
				char_pos += grp_block.list_level  # skip leading \t characters
				is_parent = grp_block.list_level == 0
				requests.extend(
					_emit_run_styles(grp_block, char_pos, force_bold=is_parent),
				)
				char_pos += sum(len(r.text) for r in grp_block.runs) + 1  # +1 for \n

			# CRITICAL: reset bullet membership before creating new bullets so
			# that text which inherited list membership from the placeholder tag
			# does not suppress the tab-based nesting logic.
			list_range = {
				"startIndex": start_index,
				"endIndex": start_index + len(full_text),
			}
			requests.append({"deleteParagraphBullets": {"range": list_range}})
			requests.append(
				{
					"updateParagraphStyle": {
						"range": list_range,
						"paragraphStyle": {},
						"fields": "indentStart,indentFirstLine",
					},
				},
			)
			requests.append(
				{
					"createParagraphBullets": {
						"range": list_range,
						"bulletPreset": (
							"BULLET_DISC_CIRCLE_SQUARE"
							if is_bullet
							else "NUMBERED_DECIMAL_NESTED"
						),
					},
				},
			)

			i = grp_start - 1
			continue

		# ── Paragraphs, headings blocks ────────────────────────────────
		para_text = "".join(r.text for r in block.runs) + "\n"
		requests.append(
			{"insertText": {"location": {"index": start_index}, "text": para_text}},
		)

		requests.extend(_emit_run_styles(block, start_index))

		para_end = start_index + len(para_text)

		if block.heading_level:
			named = {
				1: "HEADING_1",
				2: "HEADING_2",
				3: "HEADING_3",
				4: "HEADING_4",
				5: "HEADING_5",
				6: "HEADING_6",
			}
			requests.append(
				{
					"updateParagraphStyle": {
						"range": {
							"startIndex": start_index,
							"endIndex": para_end - 1,
						},
						"paragraphStyle": {
							"namedStyleType": named.get(
								block.heading_level,
								"NORMAL_TEXT",
							),
						},
						"fields": "namedStyleType",
					},
				},
			)

		i -= 1

	return requests
