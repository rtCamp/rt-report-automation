from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.output_parsers import PydanticOutputParser
from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_core.language_models import BaseLanguageModel
from langfuse import observe

from app.llm.models.summarization import ProjectSummarySchema


class StuffService:
	"""Service for summarizing documents using LangChain's stuff documents chain."""

	def __init__(
		self,
		llm: BaseLanguageModel,
		prompt: PromptTemplate,
		docs: list[Document],
	):
		"""
		Initialize the StuffService.

		Args:
			llm: The language model to use
			prompt: The prompt template
			docs: List of documents to summarize
		"""
		self.llm = llm
		self.prompt = prompt
		self.docs = docs

	@observe()
	async def summarize(self) -> ProjectSummarySchema:
		"""
		Summarize documents using LangChain's stuff documents chain.

		Returns:
			ProjectSummarySchema containing the summarized project data
		"""
		pydantic_parser = PydanticOutputParser(pydantic_object=ProjectSummarySchema)

		chain = create_stuff_documents_chain(
			llm=self.llm,
			output_parser=pydantic_parser,
			prompt=self.prompt,
		)

		return await chain.ainvoke(
			{
				"context": self.docs,
				"format_instructions": pydantic_parser.get_format_instructions(),
			},
		)
