FROM python:3.11.14-slim AS backend
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 TIKTOKEN_CACHE_DIR=/opt/tiktoken
COPY unibot_RAG/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
COPY unibot_RAG /app/unibot_RAG
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "unibot_RAG.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11.14-slim AS frontend
WORKDIR /app
COPY requirements-ui.txt /app/requirements-ui.txt
RUN pip install --no-cache-dir -r requirements-ui.txt httpx==0.28.1
COPY unibot_RAG/streamlit_chatbot.py /app/streamlit_chatbot.py
RUN useradd --create-home appuser
USER appuser
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "streamlit_chatbot.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.maxUploadSize=5"]
