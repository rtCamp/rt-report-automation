"""PII anonymization service using Microsoft Presidio."""

from __future__ import annotations

import logging
from typing import Any, cast

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

_SPACY_MODEL = "en_core_web_lg"
_logger = logging.getLogger(__name__)

_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None


def _get_engines() -> tuple[AnalyzerEngine, AnonymizerEngine]:
	"""Lazily initialize and return the Presidio analyzer and anonymizer engines.

	Uses a module-level singleton so the spaCy model is loaded only once per
	process lifetime rather than on every request.

	Returns:
		tuple[AnalyzerEngine, AnonymizerEngine]: Initialized engine pair.

	"""
	global _analyzer, _anonymizer  # noqa: PLW0603
	if _analyzer is None or _anonymizer is None:
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
	assert _analyzer is not None
	assert _anonymizer is not None
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
			Returns the original text unchanged if it is blank or no PII is found.

		"""
		if not text.strip():
			return text
		analyzer, anonymizer = _get_engines()
		results = analyzer.analyze(text=text, language="en")
		if not results:
			return text
		# Presidio analyzer/anonymizer expose equivalent RecognizerResult models from
		# different modules, which trips strict static type checks.
		anonymized = anonymizer.anonymize(
			text=text,
			analyzer_results=cast(Any, results),
		)
		return anonymized.text
