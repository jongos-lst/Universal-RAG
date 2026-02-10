import logging
import os
import tempfile

import pandas as pd
from dotenv import load_dotenv
from unibot_RAG.redis.redis_client import RedisClient
from google.cloud import storage


prefix = ''
logger = logging.getLogger(__name__)


def ingest_data_from_gcs():
    # Retrieve the bucket name from the environment
    # The default bucket name is "ggx_research", i.e. the non-prod bucket
    # For prod, please specify the bucket name "ggx-research"
    bucket_name = os.getenv("GCS_BUCKET_NAME")
    bucket = storage.Client().get_bucket(
        bucket_name
    )
    client = RedisClient.from_os_env(create_index=True)
    gcs_client = storage.Client()
    # Open a temporary file and download the file from GCS
    for blob in gcs_client.list_blobs(bucket_name, prefix = prefix):
        blob = bucket.blob(blob.name)
        if 'csv' not in str(blob.name):
            continue
        destination_file_name = os.path.join('./', f"{str(blob.name).split('/')[-1]}")
        blob.download_to_filename(destination_file_name)
        df = pd.read_csv(destination_file_name)
        client.ingest_table(df)
        logger.info(f"Successfully ingest table {str(blob.name).split('/')[-1]}!")
