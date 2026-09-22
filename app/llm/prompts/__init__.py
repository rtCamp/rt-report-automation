"""Initialization of the prompts module."""

from app.llm.prompts.audit_tips_prompt import AUDIT_TIPS_FORMAT, AUDIT_TIPS_INSTRUCTION
from app.llm.prompts.prompt import FORMAT, PII_INSTRUCTION, PREVIOUS_REPORT_INSTRUCTION

__all__ = [
	"AUDIT_TIPS_FORMAT",
	"AUDIT_TIPS_INSTRUCTION",
	"FORMAT",
	"PII_INSTRUCTION",
	"PREVIOUS_REPORT_INSTRUCTION",
]
