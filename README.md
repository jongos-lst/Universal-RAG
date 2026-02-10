# Unibot RAG Chatbot

This project, "Unibot RAG", is a Universal Retrieval Augmented Generation (RAG) chatbot designed to provide answers based on a defined knowledge base. It leverages a modern tech stack to deliver an interactive and intelligent conversational agent.

## Key Technologies and Architecture:

*   **Frontend:** Built with **Streamlit**, providing an interactive web-based chat interface (`streamlit_chatbot.py`).
*   **Backend API:** Developed using **FastAPI**, serving as the primary API for interactions (`api/main.py`).
*   **RAG Orchestration:** Utilizes **Langchain** for managing the RAG pipeline, including document retrieval and response generation (`api/unibot_langchain.py`).
*   **Large Language Model (LLM) & Embeddings:** Integrates with **OpenAI** (specifically `gpt-3.5-turbo` for LLM and `openai/text-embedding-3-small` for embeddings).
*   **Vector Store:** Employs **Redis** as a high-performance vector database to store and retrieve embedded knowledge base documents (`redis/redis_client.py`).
*   **Data Ingestion:** Data is ingested into Redis from **Google Cloud Storage** during application startup or via a dedicated API endpoint.
*   **Containerization:** The entire application is containerized using **Docker** and orchestrated with **Docker Compose** for easy setup and deployment.

The system is designed to provide precise answers from its knowledge base, explicitly stating when it lacks sufficient information to prevent hallucination, as defined in its prompt engineering.

## Building and Running

This project can be built and run using Docker Compose for local development.

### Prerequisites

*   Docker and Docker Compose installed.
*   An OpenAI API key.

### Setup Environment Variables

Create or update the `.env` file in the project root with your OpenAI API key and other configurations:

```dotenv
OPENAI_API_KEY=
REDIS_URL=redis://redis:6379
REDIS_INDEX_NAME=unibot_test
REDIS_PASSWORD=
PROJECT_NAME=unibot_RAG
API_PATH=/unibot_RAG_API
```

### Starting the Services

To start the Redis and FastAPI backend services using Docker Compose:

```bash
docker-compose up --build
```

This will:
1.  Build the `redis` service using `redis.dockerfile`.
2.  Build the `backend` service using `backend.dockerfile`.
3.  Start both services. The FastAPI backend will be accessible on port 80.

### Running the Streamlit Frontend

The Streamlit chatbot runs separately and connects directly to the Redis vector store. To run it:

```bash
streamlit run streamlit_chatbot.py
```

You can then access the Streamlit application in your web browser, typically at `http://localhost:8501`.

## Development Conventions

*   **Language:** Python 3.9+
*   **Dependency Management:** `requirements.txt`
*   **Backend Framework:** FastAPI
*   **Frontend Framework:** Streamlit
*   **RAG Framework:** Langchain
*   **Vector Database:** Redis
*   **Code Style:** Follows standard Python best practices and potentially `black` (listed in `requirements.txt`).
*   **Prompt Engineering:** Strict system prompt is used to enforce context-only answers and prevent hallucination.
