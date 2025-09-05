import json
from typing import Any, Literal

from langchain.chains.combine_documents.reduce import (
	acollapse_docs,
	split_list_of_docs,
)
from langchain.output_parsers import PydanticOutputParser
from langchain.schema import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_text_splitters import CharacterTextSplitter
from langfuse import observe
from langgraph.constants import Send
from langgraph.graph import END, START, StateGraph

from app.llm.models.summarization import ProjectSummarySchema
from app.llm.prompts import FORMAT as FORMAT_INSTRUCTIONS
from app.llm.prompts.helper import get_langfuse_prompt
from app.llm.services.map_reduce.states import OverallState, SummaryState

MAX_TOKENS = 10_000


class MapReduceSummarizationService:
	"""Map-reduce style summarization service."""

	def __init__(
		self,
		llm: BaseChatModel,
		docs: list[Document],
		max_tokens: int = MAX_TOKENS,
	) -> None:
		"""Initialize the service."""
		self.llm = llm
		self.docs = docs
		self.max_tokens = max_tokens

	@observe()
	def length_function(
		self,
		documents: list[Document],
	) -> int:
		"""Get number of tokens for input contents.

		Args:
			documents (list[Document]): List of documents.

		Returns:
			int: Number of tokens.
		"""
		return sum(self.llm.get_num_tokens(doc.page_content) for doc in documents)

	@observe()
	def generate_summary(
		self,
		state: SummaryState,
	) -> dict[str, list[str]]:
		"""Generate summary for the given document."""
		prompt = get_langfuse_prompt(
			"ai-summary-map-template",
		).invoke(
			{"context": state["content"]},
		)

		response = self.llm.invoke(prompt.to_string())
		summary = response.content
		return {
			"summaries": [
				json.dumps(summary)
				if isinstance(summary, (dict | list))
				else str(summary),
			],
		}

	def map_summaries(self, state: OverallState) -> list[Send]:
		"""Map summaries for the given state."""
		return [
			Send("generate_summary", {"content": content})
			for content in state["contents"]
		]

	def collect_summaries(self, state: OverallState):
		"""Collect summaries for the given state."""
		return {
			"collapsed_summaries": [
				Document(summary) for summary in state["summaries"]
			],
		}

	@observe()
	async def _reduce(
		self,
		docs: list[Document],
		**kwargs: Any,
	) -> str:
		"""Reduce the summaries to a final summary."""
		combined_summaries = "\n\n".join(doc.page_content for doc in docs)
		prompt_input = {"docs": combined_summaries}

		prompt = get_langfuse_prompt(
			"ai-summary-reduce-template",
		).invoke(
			{"docs": prompt_input},
		)

		response = await self.llm.ainvoke(prompt.to_string())
		summary = response.content
		if isinstance(summary, (dict | list)):
			return json.dumps(summary)
		return str(summary)

	async def collapse_summaries(self, state: OverallState):
		"""Collapse summaries for the given state."""
		doc_lists = split_list_of_docs(
			state["collapsed_summaries"],
			self.length_function,
			MAX_TOKENS,
		)
		results: list[Document] = []
		for doc_list in doc_lists:
			results.append(await acollapse_docs(doc_list, self._reduce))

		return {"collapsed_summaries": results}

	def should_collapse(
		self,
		state: OverallState,
	) -> Literal["collapse_summaries", "generate_final_summary"]:
		"""Decide whether to collapse summaries or generate final summary."""
		num_tokens = self.length_function(state["collapsed_summaries"])
		if num_tokens > MAX_TOKENS:
			return "collapse_summaries"
		return "generate_final_summary"

	@observe()
	async def generate_final_summary(
		self,
		state: OverallState,
	):
		"""Generate the final summary for the given state."""
		combined_summaries = "\n\n".join(
			doc.page_content for doc in state["collapsed_summaries"]
		)
		pydantic_parser = PydanticOutputParser(pydantic_object=ProjectSummarySchema)

		prompt = get_langfuse_prompt(
			"ai-summary-poc",
		).invoke(
			{
				"context": combined_summaries,
				"format": pydantic_parser.get_format_instructions(),
				"format_instructions": FORMAT_INSTRUCTIONS,
			},
		)

		response = await self.llm.ainvoke(prompt.to_string())

		if not isinstance(response.content, str):
			return {"final_summary": "Error: Unable to parse summary."}

		parsed_summary = pydantic_parser.parse(response.content)
		return {"final_summary": parsed_summary.model_dump_json()}

	async def summarize(self):
		"""Summarize the given contents."""

		# Nodes:
		graph = StateGraph(OverallState)
		graph.add_node("generate_summary", self.generate_summary)
		graph.add_node("collect_summaries", self.collect_summaries)
		graph.add_node("collapse_summaries", self.collapse_summaries)
		graph.add_node("generate_final_summary", self.generate_final_summary)

		# Edges:
		graph.add_conditional_edges(START, self.map_summaries, ["generate_summary"])
		graph.add_edge("generate_summary", "collect_summaries")
		graph.add_conditional_edges("collect_summaries", self.should_collapse)
		graph.add_conditional_edges("collapse_summaries", self.should_collapse)
		graph.add_edge("generate_final_summary", END)

		app = graph.compile()

		text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
			chunk_size=MAX_TOKENS,
			chunk_overlap=0,
		)
		split_docs = text_splitter.split_documents(self.docs)

		map_reduce_summary = ""
		async for step in app.astream(
			{
				"contents": [doc.page_content for doc in split_docs],
				"summaries": [],
				"collapsed_summaries": [],
				"final_summary": "",
			},
			{"recursion_limit": 10},
		):
			if "generate_final_summary" in step:
				map_reduce_summary = step["generate_final_summary"]["final_summary"]

		return map_reduce_summary
