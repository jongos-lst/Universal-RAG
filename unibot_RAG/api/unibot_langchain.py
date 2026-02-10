import logging
import os
import time
from typing import Literal
import pandas as pd

import openai
from dotenv import load_dotenv
from fastapi import FastAPI
from unibot_RAG.api.prompt import chat_prompt
from unibot_RAG.redis_db.redis_client import RedisClient
from langchain.callbacks import get_openai_callback
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferWindowMemory
from pydantic import BaseModel, Field

import requests

load_dotenv()
app = FastAPI()
class unibot_RAG:
    def __init__(self, vector_store, memory: bool = False) -> None:
        """
        vector_store: the vector_store that store context tables
        memory: enable/disable ConversationBufferWindowMemory
        """

        self.logger = logging.getLogger(__name__)
        self.llm = ChatOpenAI(
            model_name="openai/gpt-oss-120b:free",
            base_url="https://openrouter.ai/api/v1",
            temperature=0,
            max_tokens=2048,
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
        self.logger.info(f"Using model {self.llm.model_name}")
        self.api_url = os.getenv("unibot_API_URL")
        self.vector_store = vector_store

        if memory:
            self.logger.info("Using ConversationBufferWindowMemory")
            self.qa = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=vector_store.as_retriever(search_kwargs={"k": 1}),
                return_source_documents=False,
                chain_type_kwargs={"prompt": chat_prompt, "verbose": True},
                memory=ConversationBufferWindowMemory(k=42),
            )
        else:
            self.logger.info("Not using ConversationBufferWindowMemory")
            self.qa = RetrievalQA.from_chain_type(
                llm=self.llm,
                chain_type="stuff",
                retriever=vector_store.as_retriever(search_kwargs={"k": 1}),
                return_source_documents=True,
                chain_type_kwargs={"prompt": chat_prompt, "verbose": True},
            )

    def contains_keyword(self, input_string, keyword_list):
        """
        Check if the input string contains any of the keywords in the provided list.

        :param input_string: The string to be checked.
        :param keyword_list: A list of keywords to check against.
        :return: True if any keyword is found in the input string, False otherwise.
        """
        for keyword in keyword_list:
            if keyword in input_string:
                return True
        return False

    def get_response(self, query: str) -> dict:
        """
        inputs:
            query (str): user query

        outputs:
            response (str): answer query with llm + designed prompt + 'answer' in the faq_table
            service (str): triggered service (default:''). will be set when inputted user query includes related intent, e.g., 'order_placement',  'order_cancel', etc...
            metadata (dict): metadata of the source document
            source_document (str): source document of the response, i.e. the original answer in the faq_df
        """

        with get_openai_callback() as cb:
            result = self.qa(query)
            self.logger.debug(f"OpenAI API call: {cb}")
            self.logger.debug(result)

            metadata = result["source_documents"][0].metadata
            self.logger.info(f"Answer: {result['result']}")

            # * We return the source document (i.e. the answer) because
            # * Langchain pop it from the metadata
            return {
                "answer": result["result"],
                "metadata": metadata,
                "source_document": result["source_documents"][0].page_content,
            }


    def apply(self, examples: list) -> list:
        """
        wrapper for evaluation
        """
        return self.qa.apply(examples)
