"""Compatibility helpers; all new ingestion uses canonical document loaders."""

from unibot_RAG.config import Settings
from unibot_RAG.ingestion.loaders import load_documents
from unibot_RAG.ingestion.sources import fetch_website

DF_SCHEMA = ["Question", "Answer", "Context", "uuid"]


def check_schema(df):
    if not set(DF_SCHEMA) <= set(df.columns):
        raise ValueError("FAQ columns must include Question, Answer, Context and uuid")
    return df[DF_SCHEMA]


def process_df_for_vectorstore(df, text_splitter):
    import hashlib

    texts, metadata, ids = [], [], []
    for _, row in check_schema(df).iterrows():
        content = "\n".join(
            f"{name}: {row[name]}" for name in ["Question", "Answer", "Context"]
        )
        for index, chunk in enumerate(text_splitter.split_text(content)):
            texts.append(chunk)
            metadata.append(
                {
                    "question": str(row["Question"]),
                    "answer": str(row["Answer"]),
                    "uuid": str(row["uuid"]),
                }
            )
            ids.append(
                hashlib.sha256(f"{row['uuid']}:{index}:{chunk}".encode()).hexdigest()
            )
    return texts, metadata, ids


def extract_website_content(url):
    settings = Settings()
    page = fetch_website(url, settings)
    return "\n\n".join(
        doc.text for doc in load_documents(page.filename, page.content, url, settings)
    )
