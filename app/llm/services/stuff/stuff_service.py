"""Service for summarizing documents using LangChain's stuff documents chain."""

from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.output_parsers import PydanticOutputParser
from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_core.language_models import BaseLanguageModel
from langfuse import observe

from app.core.adapters.langfuse import langfuse, traced_chain_ainvoke
from app.llm.models.summarization import ProjectSummarySchema
from app.llm.prompts.prompt import FORMAT, PREVIOUS_REPORT_INSTRUCTION


class StuffService:
	"""Service for summarizing documents using LangChain's stuff documents chain."""

	def __init__(
		self,
		llm: BaseLanguageModel,
		docs: list[Document],
		prompt_slug: str = "ai-summary-poc",
		previous_report: str | None = None,
	):
		"""Initialize the StuffService.

		Args:
			llm: The language model to use
			docs: List of documents to summarize
			prompt_slug: The slug/identifier for the prompt template
			previous_report: Optional Markdown content of the previous report

		"""
		self.llm = llm
		self.docs = docs
		self.prompt_slug = prompt_slug
		self.previous_report = previous_report

	@observe(name="stuff_summarize")
	async def summarize(self) -> str:
		"""Summarize documents using LangChain's stuff documents chain.

		Returns:
			str: JSON string containing the summarized project data

		"""
		pydantic_parser = PydanticOutputParser(pydantic_object=ProjectSummarySchema)

		langfuse_prompt = langfuse.get_prompt(self.prompt_slug)

		prompt_template = langfuse_prompt.get_langchain_prompt(format=FORMAT)
		if self.previous_report:
			# Prepend instruction so the LLM sees it before the main task
			prompt_template = (
				f"{PREVIOUS_REPORT_INSTRUCTION}\n"
				f"{prompt_template}\n\n"
				f"--- PREVIOUS REPORT (for reference only) ---\n"
				f"{{previous_report}}"
			)

		prompt = PromptTemplate.from_template(prompt_template)

		chain = create_stuff_documents_chain(
			llm=self.llm,
			output_parser=pydantic_parser,
			prompt=prompt,
		)

		invoke_params: dict = {
			"context": self.docs,
			"format_instructions": pydantic_parser.get_format_instructions(),
		}

		if self.previous_report:
			invoke_params["previous_report"] = self.previous_report

		result = await traced_chain_ainvoke(chain, invoke_params)

		return result.model_dump_json()
