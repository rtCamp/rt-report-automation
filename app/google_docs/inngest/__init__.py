"""Inngest functions for Google Docs integration."""

from app.google_docs.inngest.fetch_previous_report import fetch_previous_report
from app.google_docs.inngest.main import generate_google_doc

__all__ = ["fetch_previous_report", "generate_google_doc"]
