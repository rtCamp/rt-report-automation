"""PII anonymization service using Microsoft Presidio."""

import logging
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
	global _analyzer, _anonymizer  # noqa: PLW0603

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
	"""

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
