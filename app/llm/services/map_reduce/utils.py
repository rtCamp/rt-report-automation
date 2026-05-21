"""Utility helpers for map-reduce summarization.

Replaces langchain.chains.combine_documents.reduce (removed in langchain 1.x).
"""

from collections.abc import Callable, Coroutine
from typing import Any

from langchain_core.documents import Document


def split_list_of_docs(
	docs: list[Document],
	length_func: Callable[[list[Document]], int],
	token_max: int,
) -> list[list[Document]]:
	"""Split a list of Documents into sublists each within token_max tokens."""
	new_doc_list: list[list[Document]] = [[]]
	for doc in docs:
		new_doc_list[-1].append(doc)
		if length_func(new_doc_list[-1]) > token_max:
			last_doc = new_doc_list[-1].pop()
			new_doc_list.append([last_doc])
	return new_doc_list


async def acollapse_docs(
	docs: list[Document],
	combine_fn: Callable[[list[Document]], Coroutine[Any, Any, str]],
) -> Document:
	"""Collapse a list of Documents into a single Document via combine_fn."""
	combined = await combine_fn(docs)
	return Document(page_content=combined)
