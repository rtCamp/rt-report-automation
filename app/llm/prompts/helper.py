"""Helper functions for managing prompts."""

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langfuse import observe

from app.core.adapters.langfuse import langfuse


@observe(name="fetch_langfuse_prompt")
def get_langfuse_prompt(name: str, label: str = "production") -> ChatPromptTemplate:
	"""Get a ChatPromptTemplate from Langfuse.

	Args:
		name: The name of the prompt in Langfuse
		label: The label/version of the prompt (default: "production")

	Returns:
		ChatPromptTemplate: The prompt template ready for use

	"""
	template = langfuse.get_prompt(name, label=label).get_langchain_prompt()

	return ChatPromptTemplate(
		messages=[SystemMessagePromptTemplate.from_template(template)],
	)
