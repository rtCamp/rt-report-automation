"""Conservative prompt sanitization for LLM inputs.

Removes or neutralises known prompt-injection and jailbreak patterns before
text reaches any language model. Unicode input is NFKC-normalised first so
that full-width and compatibility-character obfuscation is caught automatically.

All five conservative pattern groups are always applied:
    1. Critical instruction overrides and tag injection
    2. Context / session reset directives
    3. Role-play and safety-bypass directives
    4. Encoding attacks (Base64, hex, Unicode escapes)
    5. Character-level obfuscation
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern group 1 — Critical instruction overrides & tag injection
# ---------------------------------------------------------------------------
_CRITICAL_PATTERNS: list[tuple[str, str]] = [
	# "ignore [all] previous/prior/above/earlier/all instructions/rules/prompts"
	(
		r"ignore\s+(all\s+)?(previous|prior|above|earlier|all)"
		r"\s+(instructions?|rules?|prompts?)",
		"",
	),
	# "forget everything/all/prior/previous instructions"
	(r"forget\s+(everything|all|prior|previous|instructions?)", ""),
	# "disregard previous/prior/above/all instructions/context/rules"
	(
		r"disregard\s+(previous|prior|above|all)"
		r"\s+(instructions?|context|rules?)",
		"",
	),
	# developer / debug / admin / sudo / root mode
	(r"(developer|debug|admin|sudo|root)\s+mode", ""),
	# "you are now a/an <role>"
	(r"\byou\s+are\s+now\s+(a|an)\s+\w+", "you are an AI assistant"),
	# DAN jailbreak token
	(r"\bdan\b(?!\w)", ""),
	# "do anything now"
	(r"do\s+anything\s+now", ""),
	# requests to reveal / print / show / display the system prompt
	(r"(print|show|reveal|display)\s+(your\s+)?(system\s+)?prompt", ""),
	# "repeat the previous/above/initial instructions/text"
	(r"repeat\s+(the\s+)?(above|previous|initial)\s+(instructions?|text)", ""),
	# XML-style role tags: </system>, <user>, etc.
	(r"</?(system|user|assistant)>", ""),
	# LLaMA instruction markers
	(r"\[/?INST\]", ""),
	(r"<</?SYS>>", ""),
]

# ---------------------------------------------------------------------------
# Pattern group 2 — Context / session reset directives
# ---------------------------------------------------------------------------
_CONTEXT_RESET_PATTERNS: list[tuple[str, str]] = [
	(r"start\s+(over|fresh|anew)", "continue"),
	(r"new\s+(conversation|context|session)", "current conversation"),
	(r"(clear|reset|wipe)\s+(your\s+)?(memory|context)", ""),
]

# ---------------------------------------------------------------------------
# Pattern group 3 — Role-play and safety-bypass directives
# ---------------------------------------------------------------------------
_ROLEPLAY_BYPASS_PATTERNS: list[tuple[str, str]] = [
	# "act as / pretend to be / roleplay as a/an <role>"
	(r"(act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(a|an)\s+\w+", "help with"),
	# "ignore/bypass/disable/remove safety/security/restrictions"
	(
		r"(ignore|bypass|disable|remove)\s+(safety|security|restrictions?)",
		"",
	),
	# "no restrictions / no limits / no rules / no filters"
	(r"no\s+(restrictions?|limits?|rules?|filters?)", ""),
	# "respond only/exclusively with"
	(r"respond\s+(only|exclusively)\s+with", "respond with"),
	# "always/only respond/reply/answer in/with/as"
	(r"(always|only)\s+(respond|reply|answer)\s+(in|with|as)", "respond"),
]

# ---------------------------------------------------------------------------
# Pattern group 4 — Encoding attacks
# ---------------------------------------------------------------------------
_ENCODING_PATTERNS: list[tuple[str, str]] = [
	# Base64 payload (30+ chars with optional padding)
	(r"(?<!\w)[A-Za-z0-9+/]{30,}={0,2}(?!\w)", "[removed]"),
	# Hex escape sequences: \xNN repeated 4+ times
	(r"(?:\\x[0-9a-fA-F]{2}){4,}", "[removed]"),
	# Unicode escape sequences: \uNNNN repeated 3+ times
	(r"(?:\\u[0-9a-fA-F]{4}){3,}", "[removed]"),
]

# ---------------------------------------------------------------------------
# Pattern group 5 — Character-level obfuscation
# ---------------------------------------------------------------------------
_OBFUSCATION_PATTERNS: list[tuple[str, str]] = [
	# Spaced-letter obfuscation: "i g n o r e" → "ignore"
	(r"\b([a-z])\s+([a-z])\s+([a-z])\s+([a-z])\s+([a-z])\b", r"\1\2\3\4\5"),
	# Common leetspeak variants
	(r"\b1gn[0o]r[e3]\b", "ignore"),
	(r"\bbyp[4a]ss\b", "bypass"),
	(r"\b[0o]v[e3]rr[1i]d[e3]\b", "override"),
	# Excessive punctuation: "!!!" → "!"
	(r"([.!?])\1{2,}", r"\1"),
]

# ---------------------------------------------------------------------------
# Pre-compiled pattern lists (built once at import time)
# ---------------------------------------------------------------------------
def _compile(
	raw: list[tuple[str, str]],
) -> list[tuple[re.Pattern[str], str]]:
	compiled: list[tuple[re.Pattern[str], str]] = []
	for pattern, replacement in raw:
		try:
			compiled.append((re.compile(pattern, re.IGNORECASE), replacement))
		except re.error as exc:
			logger.warning("Failed to compile sanitizer pattern %r: %s", pattern, exc)
	return compiled


_COMPILED_CRITICAL = _compile(_CRITICAL_PATTERNS)
_COMPILED_CONTEXT_RESET = _compile(_CONTEXT_RESET_PATTERNS)
_COMPILED_ROLEPLAY_BYPASS = _compile(_ROLEPLAY_BYPASS_PATTERNS)
_COMPILED_ENCODING = _compile(_ENCODING_PATTERNS)
_COMPILED_OBFUSCATION = _compile(_OBFUSCATION_PATTERNS)

# Order matters: obfuscation must be resolved before the semantic patterns run
_ALL_PATTERNS: list[tuple[re.Pattern[str], str]] = (
	_COMPILED_OBFUSCATION
	+ _COMPILED_CRITICAL
	+ _COMPILED_CONTEXT_RESET
	+ _COMPILED_ROLEPLAY_BYPASS
	+ _COMPILED_ENCODING
)

# Whitespace normalization helpers (module-level to avoid re-instantiation)
_WS_RE = re.compile(r"\s+")
_PUNCT_WS_RE = re.compile(r"\s+([,.!?])")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _apply_patterns(text: str) -> str:
	"""Apply all conservative pattern groups to *text* and return the result."""
	for pattern, replacement in _ALL_PATTERNS:
		text = pattern.sub(replacement, text)
	return text


def _clean_whitespace(text: str) -> str:
	"""Collapse multiple spaces and strip leading/trailing whitespace."""
	text = _WS_RE.sub(" ", text)
	text = _PUNCT_WS_RE.sub(r"\1", text)
	return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def sanitize_prompt(text: str) -> str:
	"""Sanitize *text* using conservative prompt-injection defenses.

	Applies NFKC Unicode normalisation followed by all five conservative
	pattern groups (instruction overrides, context resets, role-play/bypass
	directives, encoding attacks, and character-level obfuscation).

	Args:
		text: Raw prompt or document text to sanitize.

	Returns:
		The sanitized string.  If sanitization fails for any reason the
		original *text* is returned unchanged so the pipeline is never broken.

	"""
	if not text or not text.strip():
		return text

	try:
		return _clean_whitespace(_apply_patterns(unicodedata.normalize("NFKC", text)))
	except Exception:
		logger.exception("Prompt sanitization failed; returning original text")
		return text
