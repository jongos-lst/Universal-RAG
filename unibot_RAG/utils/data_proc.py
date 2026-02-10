from __future__ import annotations

import pandas as pd

import requests
from bs4 import BeautifulSoup
import re

DF_SCHEMA = [
    "Question",
    "Answer",
    "Context",
    "uuid",
]


def check_schema(df: pd.DataFrame):
    try:
        df = df[DF_SCHEMA]
    except KeyError:
        raise KeyError("Schema not match!")

    return df


def process_df_for_vectorstore(df, text_splitter):
    """
    Process DataFrame for vectorstore
    1. Check if schema is correct
    2. Split text into chunks
    3. Add metadata
    """
    batched_texts = []
    batched_metadatas = []
    batched_ids = []

    from tqdm import tqdm

    df = check_schema(df)

    for _, row in tqdm(df.iterrows(), total=df.shape[0]):
        # Embedding based on question and keywords
        texts = text_splitter.split_text(row["Context"])
        n = len(texts)

        # There's definitely some better way to do this
        metadata_dict = {
            "question": row["Question"],
            "answer": row["Answer"],
            "uuid": row["uuid"],
        }

        batched_texts.extend(texts)
        batched_metadatas.extend([metadata_dict for _ in range(n)])
        batched_ids.extend([row["uuid"] for _ in range(n)])

    return batched_texts, batched_metadatas, batched_ids

def extract_website_content(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script_or_style in soup(['script', 'style', 'header', 'footer', 'nav']):
            script_or_style.decompose()
            
        # Get text and clean it
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Additional cleaning
        text = re.sub(r'\n+', '\n', text)  # Replace multiple newlines with a single one
        text = re.sub(r'\s+', ' ', text)  # Replace multiple spaces with a single one
        
        return text
    except Exception as e:
        return None
