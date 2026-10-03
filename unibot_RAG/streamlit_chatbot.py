"""UI talks to the API so ingestion and retrieval use the same contracts."""

import os
import httpx
import streamlit as st

st.set_page_config(page_title="Universal RAG", page_icon="📚")
st.title("Universal RAG")
st.caption("Ask questions with cited document evidence, or draft SQL using WrenAI.")
api_url = os.getenv("RAG_API_URL", "http://127.0.0.1:8000").rstrip("/")


def request(method, path, **kwargs):
    try:
        with httpx.Client(base_url=api_url, timeout=120) as client:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        st.error(
            f"Request failed ({exc.response.status_code}). Check the input, configuration or service availability."
        )
    except httpx.HTTPError:
        st.error("The API is unavailable. Check that the backend is running.")
    return None


with st.sidebar:
    st.header("Knowledge sources")
    admin_token = st.text_input("Administrator token", type="password")
    source_id = st.text_input("Source ID", placeholder="team-handbook")
    uploaded = st.file_uploader(
        "Upload a document",
        type=["txt", "md", "html", "csv", "json", "jsonl", "pdf", "docx"],
    )
    if st.button(
        "Ingest document", disabled=uploaded is None or not source_id or not admin_token
    ):
        with st.spinner("Parsing, chunking and indexing…"):
            report = request(
                "POST",
                "/v1/admin/upload",
                headers={"Authorization": "Bearer " + admin_token},
                data={"source_id": source_id},
                files={"file": (uploaded.name, uploaded.getvalue())},
            )
        if report:
            st.session_state["ingestion_report"] = report
    website = st.text_input("Website URL", placeholder="https://example.com/guide")
    st.caption("Website hosts must be allowed in the server configuration.")
    if st.button("Ingest website", disabled=not website or not admin_token):
        with st.spinner("Fetching and indexing…"):
            report = request(
                "POST",
                "/v1/admin/website",
                headers={"Authorization": "Bearer " + admin_token},
                json={"url": website},
            )
        if report:
            st.session_state["ingestion_report"] = report
    if "ingestion_report" in st.session_state:
        report = st.session_state["ingestion_report"]
        st.write(f"Status: {report['status']}")
        st.write(f"Chunks: {report['chunk_count']}")
        st.code(report["job_id"], language=None)
        for warning in report.get("warnings", []):
            st.warning(warning)

mode = st.radio("Question mode", ["Document answer", "SQL proposal"], horizontal=True)
if mode == "SQL proposal":
    st.info(
        "Requires configured WrenAI. SQL is generated and transpiled, never executed."
    )
question = st.text_area(
    "Your question", max_chars=4000, placeholder="What is the return policy?"
)
if st.button("Ask", type="primary", disabled=not question.strip()):
    st.session_state.pop("last_result", None)
    path = (
        "/v1/sql/propose"
        if mode == "SQL proposal"
        else "/unibot/v1/users/get-unibot-response/"
    )
    with st.spinner("Looking for supporting evidence…"):
        result = request("POST", path, json={"question": question})
    if result:
        st.session_state["last_result"] = result
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    if "sql" in result:
        st.code(result["sql"], language="sql")
        st.caption("Wren transpilation completed. Query has not been executed.")
    else:
        st.write(result["answer"])
        for number, source in enumerate(result.get("sources", []), 1):
            with st.expander(f"Source {number}: {source['source_id']}"):
                st.text(source["text"])
                st.json(source.get("metadata", {}))
