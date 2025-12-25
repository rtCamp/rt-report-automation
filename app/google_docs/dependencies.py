"""Dependency injection for Google Docs module."""

from functools import lru_cache

from app.google_docs.services.google_docs import GoogleDocsService


@lru_cache
def get_google_docs_service() -> GoogleDocsService:
	"""Get or create a singleton GoogleDocsService instance.

	This function is cached to ensure the same service instance
	is reused across requests, allowing credential caching to work
	effectively. The underlying GoogleAuthService maintains cached
	credentials that are shared across all requests.

	Returns:
		GoogleDocsService: Singleton service instance.

	"""
	return GoogleDocsService()
