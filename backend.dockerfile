FROM python:3.11.6

RUN python3 -m ensurepip
RUN pip3 install --no-cache --upgrade pip setuptools 

WORKDIR /app/
ENV PYTHONPATH=/app

COPY unibot_RAG/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY unibot_RAG /app/unibot_RAG
RUN chmod +x unibot_RAG/start-uvicorn.sh

RUN addgroup docker && adduser --system appuser && adduser appuser docker && chown appuser:docker -R /app/* 
USER appuser
WORKDIR /app/unibot_RAG
# CMD ./start-uvicorn.sh
ENTRYPOINT ["streamlit", "run", "streamlit_chatbot.py", "--server.port=8501", "--server.address=0.0.0.0"]
