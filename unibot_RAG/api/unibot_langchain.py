"""Legacy import adapter. New callers should use RAGService directly."""

from unibot_RAG.service import RAGService


class unibot_RAG:
    def __init__(self, service: RAGService, memory=False):
        if memory:
            raise ValueError(
                "Conversation memory is not supported; queries are isolated"
            )
        if not isinstance(service, RAGService):
            raise TypeError(
                "Pass a RAGService; legacy LangChain vector stores require reingestion"
            )
        self.service = service

    def get_response(self, query):
        return self.service.answer(query)

    def apply(self, examples):
        return [self.get_response(item["query"]) for item in examples]
