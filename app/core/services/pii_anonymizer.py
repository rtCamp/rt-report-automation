"""PII anonymization service using Microsoft Presidio."""

import logging
import re
import threading
from typing import Any, cast

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

from app.core.utils import log_and_raise, validate

_SPACY_MODEL = "en_core_web_lg"
_logger = logging.getLogger(__name__)

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None
_init_lock = threading.Lock()


def _get_engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
	"""Lazily initialize and return the Presidio analyzer and anonymizer engines.

	Uses a module-level singleton so the spaCy model is loaded only once per
	process lifetime rather than on every request. Thread-safe initialization
	with a threading lock ensures no race conditions on concurrent first access.

	Returns:
		tuple[AnalyzerEngine, AnonymizerEngine]: Initialized engine pair.

	Raises:
		RuntimeError: If engine initialization fails.

	"""
	global _analyzer, _anonymizer

	if _analyzer is not None and _anonymizer is not None:
		return _analyzer, _anonymizer

	with _init_lock:
		if _analyzer is not None and _anonymizer is not None:
			return _analyzer, _anonymizer

		try:
			provider = NlpEngineProvider(
				nlp_configuration={
					"nlp_engine_name": "spacy",
					"models": [{"lang_code": "en", "model_name": _SPACY_MODEL}],
				}
			)
			nlp_engine = provider.create_engine()
			_analyzer = AnalyzerEngine(
				nlp_engine=nlp_engine,
				supported_languages=["en"],
			)
			_anonymizer = AnonymizerEngine()
		except FileNotFoundError as e:
			log_and_raise(
				_logger,
				f"Required spaCy model '{_SPACY_MODEL}' not installed",
				RuntimeError,
				cause=e,
			)
		except Exception as e:
			log_and_raise(
				_logger,
				"Failed to initialize Presidio analyzer/anonymizer engines",
				RuntimeError,
				cause=e,
			)

		if _analyzer is None or _anonymizer is None:
			log_and_raise(
				_logger,
				"Presidio engines returned None after initialization",
				RuntimeError,
			)

	return _analyzer, _anonymizer


class PIIAnonymizer:
	"""Detects and anonymizes PII in free-form text using Microsoft Presidio.

	Entities detected by the Presidio ``AnalyzerEngine`` (backed by the
	``en_core_web_lg`` spaCy model) are replaced with their entity-type label,
	e.g. ``<PERSON>``, ``<EMAIL_ADDRESS>``, so that LLM prompts never receive
	raw personal information.

	For reversible anonymization, use ``anonymize_with_mapping`` which assigns
	unique numbered placeholders (e.g. ``<PERSON_1>``, ``<ORGANIZATION_2>``)
	and tracks a mapping for later de-anonymization. Call it multiple times on
	the same instance to maintain consistent placeholders across documents.
	"""

	def __init__(self):
		"""Initialize PIIAnonymizer with empty mapping state."""
		self._mapping: dict[str, str] = {}
		self._reverse_lookup: dict[str, str] = {}
		self._counters: dict[str, int] = {}

	@property
	def mapping(self) -> dict[str, str]:
		"""Return a copy of the current placeholder-to-original mapping."""
		return dict(self._mapping)

	def anonymize(self, text: str) -> str:
		"""Anonymize PII in the given text.

		Args:
			text: Input text that may contain PII.

		Returns:
			Text with all detected PII replaced by ``<ENTITY_TYPE>`` placeholders.
			Returns the original text unchanged if it is blank, no PII is found,
			or if anonymization fails for any reason.

		Raises:
			TypeError: If text is not a string.

		"""
		validate(text, str)

		if not text.strip():
			return text

		try:
			analyzer, anonymizer = _get_engines()
		except RuntimeError:
			_logger.warning(
				"PII anonymizer engines unavailable; returning text unchanged"
			)
			return text

		try:
			results = analyzer.analyze(text=text, language="en")
		except Exception as e:
			_logger.warning("PII analyzer failed: %s; returning text unchanged", e)
			return text

		if not results:
			return text

		try:
			anonymized = anonymizer.anonymize(
				text=text,
				analyzer_results=cast("Any", results),
			)
		except Exception as e:
			_logger.warning("PII anonymizer failed: %s; returning text unchanged", e)
			return text

		if anonymized is None or not hasattr(anonymized, "text"):
			_logger.warning(
				"PII anonymizer returned invalid response structure; "
				"returning text unchanged"
			)
			return text

		sanitized_text = anonymized.text
		if not isinstance(sanitized_text, str):
			_logger.warning(
				"PII anonymizer.text is not a string (type: %s); "
				"returning text unchanged",
				type(sanitized_text).__name__,
			)
			return text

		return sanitized_text

	def anonymize_with_mapping(self, text: str) -> str:
		"""Anonymize PII with unique numbered placeholders for reversibility.

		Uses numbered placeholders like ``<PERSON_1>``, ``<ORGANIZATION_2>``
		instead of generic ``<ENTITY_TYPE>`` tags. Tracks a mapping so that
		``deanonymize`` can restore original values.

		Call this method multiple times on the same instance to maintain
		consistent placeholders across documents (same original value always
		gets the same placeholder).

		Args:
			text: Input text that may contain PII.

		Returns:
			Text with PII replaced by unique numbered placeholders.
			Returns the original text unchanged if blank, no PII is found,
			or if analysis fails.

		Raises:
			TypeError: If text is not a string.

		"""
		validate(text, str)

		if not text.strip():
			return text

		try:
			analyzer, _ = _get_engines()
		except RuntimeError:
			_logger.warning(
				"PII anonymizer engines unavailable; returning text unchanged",
			)
			return text

		try:
			results = analyzer.analyze(text=text, language="en")
		except Exception as e:
			_logger.warning("PII analyzer failed: %s; returning text unchanged", e)
			return text

		if not results:
			return text

		# Sort by start position descending so replacements don't shift indices
		sorted_results = sorted(results, key=lambda r: r.start, reverse=True)

		for result in sorted_results:
			original = text[result.start : result.end]

			if original in self._reverse_lookup:
				placeholder = self._reverse_lookup[original]
			else:
				entity_type = result.entity_type
				self._counters[entity_type] = self._counters.get(entity_type, 0) + 1
				placeholder = f"<{entity_type}_{self._counters[entity_type]}>"
				self._reverse_lookup[original] = placeholder
				self._mapping[placeholder] = original

			text = text[: result.start] + placeholder + text[result.end :]

		return text

	@staticmethod
	def deanonymize(
		data: str | dict | list,
		mapping: dict[str, str],
	) -> str | dict | list:
		"""Restore original values from numbered placeholders.

		Accepts a string, dict, or list and recursively replaces all
		placeholders found in string values.  Operating on a parsed data
		structure (rather than raw JSON text) avoids the risk of injecting
		unescaped characters that would break JSON serialization.

		Args:
			data: Anonymized data — a string, dict, or list.
			mapping: Placeholder-to-original mapping from ``mapping`` property.

		Returns:
			Data with placeholders replaced by original values.

		"""
		if isinstance(data, dict):
			return {
				key: PIIAnonymizer.deanonymize(value, mapping)
				for key, value in data.items()
			}
		if isinstance(data, list):
			return [PIIAnonymizer.deanonymize(item, mapping) for item in data]
		if isinstance(data, str):
			# Sort by placeholder length descending to prevent prefix collisions
			# (e.g., <PERSON_1> matching inside <PERSON_10>).
			for placeholder, original in sorted(
				mapping.items(), key=lambda item: len(item[0]), reverse=True
			):
				# Replace exact form: <PERSON_1>
				data = data.replace(placeholder, original)
				# Also replace bare form (e.g. PERSON_1) in case the LLM stripped
				# the surrounding angle brackets from the placeholder. Word
				# boundaries prevent PERSON_1 from matching inside PERSON_10.
				bare = re.escape(placeholder[1:-1])
				data = re.sub(
					r"\b" + bare + r"\b",
					lambda m, orig=original: orig,
					data,
				)
			return data
		return data
