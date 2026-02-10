import hashlib
import logging
import os

import pandas as pd
import tiktoken
from unibot_RAG.utils.data_proc import process_df_for_vectorstore
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores.redis import Redis


schema = {
    'text': [{'name': 'question', 'weight': 1, 'no_stem': False, 'withsuffixtrie': False, 'no_index': False, 'sortable': False},
             {'name': 'answer', 'weight': 1, 'no_stem': False, 'withsuffixtrie': False, 'no_index': False, 'sortable': False}, 
             {'name': 'uuid', 'weight': 1, 'no_stem': False, 'withsuffixtrie': False, 'no_index': False, 'sortable': False}, 
             {'name': 'original_uuid', 'weight': 1, 'no_stem': False, 'withsuffixtrie': False, 'no_index': False, 'sortable': False},
             ],
     'vector': [{'name': 'content_vector', 'dims': 1536, 'algorithm': 'FLAT', 'datatype': 'FLOAT32', 'distance_metric': 'COSINE', 'initial_cap': 20000, 'block_size': 1000}], 'content_key':'answer'}



class RedisClient:
    def __init__(
        self,
        index_name: str,
        create_index: bool = False,
    ) -> None:
        self.create_index = create_index
        self.index_name = index_name
        self.tokenizer = tiktoken.get_encoding("p50k_base")
        self.logger = logging.getLogger(__name__)

        self.tiktoken_len = lambda text: len(
            self.tokenizer.encode(text, disallowed_special=())
        )

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400,
            chunk_overlap=20,
            length_function=self.tiktoken_len,
            separators=["\n\n", "\n", " ", ""],
        )

        model_name = "openai/text-embedding-3-small"
        self.embedding = OpenAIEmbeddings(
            model=model_name,
            openai_api_base="https://openrouter.ai/api/v1",
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )


        if not create_index:
            self.logger.info(f"Connecting to Redis index {self.index_name}")
            self.vectorstore = Redis(
                redis_url=os.getenv("REDIS_URL"),
                index_name=index_name,
                embedding=self.embedding,
                index_schema=schema,
                username=os.getenv("REDIS_USER"),
                password=os.getenv("REDIS_PASSWORD"),
            )
            self.logger.info(
                f"Connected to Redis index {self.index_name} on {os.getenv('REDIS_URL')}"
            )
        else:
            self.logger.info(
                f"Please create Redis index {self.index_name} after __init__ by calling `ingest_table` or `ingest_document`"
            )

        self.batch_size = 64

    def ingest_table(self, df: pd.DataFrame):
        """
        Ingest a table of questions and answers into the index on pinecone.

        The dataframe should be pre-processed through the function `proc_faq_df` in `utils.py.
        """

        assert "Context" in df.columns
        assert "uuid" in df.columns

        texts, metadatas = process_df_for_vectorstore(df, self.text_splitter)

        self.logger.info(f"Ingesting {len(df)} rows into Redis index {self.index_name}")
        self.vectorstore = Redis.from_texts(
            texts=texts,
            metadatas=metadatas,
            embedding=self.embedding,
            index_name=self.index_name,
            index_schema=schema,
            username=os.getenv("REDIS_USER"),
            password=os.getenv("REDIS_PASSWORD"),
        )
        self.logger.info(f"Ingested {len(df)} rows into Redis index {self.index_name}")

    def ingest_document(self, text: str):
        texts = self.text_splitter.split_text(text)
        n = len(texts)
        metadatas = [
            {
                "index": i,
                "text": texts[i],
            }
            for i in range(n)
        ]
        
        ids = [hashlib.md5(text.encode()).hexdigest() for text in texts]

        embeddings = self.embedding.embed_documents(texts, chunk_size=self.batch_size)

        self.logger.info(f"Ingesting document into Redis index {self.index_name}")
        self.vectorstore.add_texts(
            texts=texts, metadatas=metadatas, embeddings=embeddings, ids=ids
        )
        self.logger.info(f"Ingested document into Redis index {self.index_name}")

    def reset(self):
        self.vectorstore.drop_index(self.index_name, delete_documents=True)
        self.logger.info(f"Dropped Redis index {self.index_name}")

    @property
    def info(self) -> str:
        raise NotImplementedError

    @classmethod
    def from_os_env(cls, create_index: bool = False):
        return cls(
            index_name=os.getenv("REDIS_INDEX_NAME"),
            create_index=create_index,
        )
