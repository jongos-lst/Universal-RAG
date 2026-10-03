import os
from pathlib import Path
from types import SimpleNamespace
from streamlit.testing.v1 import AppTest
from unittest.mock import patch
import httpx

result = {
    "answer": "Returns accepted within 30 days.",
    "sources": [
        {
            "source_id": "policy",
            "text": "Return within 30 days.",
            "metadata": {"page": 1},
        }
    ],
}


def request(self, method, path, **kwargs):
    return httpx.Response(
        200, json=result, request=httpx.Request(method, "http://test" + path)
    )


with patch.object(httpx.Client, "request", request):
    app = AppTest.from_file(
        os.getenv(
            "UI_APP_PATH",
            str(
                Path(__file__).resolve().parents[1] / "unibot_RAG/streamlit_chatbot.py"
            ),
        )
    ).run()
    assert not app.exception
    assert app.button[0].disabled and app.button[1].disabled and app.button[2].disabled
    app.text_area[0].input("What is the return policy?").run()
    next(b for b in app.button if b.label == "Ask").click().run()
    assert not app.exception
    assert any("Returns accepted" in m.value for m in app.markdown)
    assert app.expander[0].label == "Source 1: policy"
    result = {"sql": "SELECT SUM(amount) FROM orders", "executed": False}
    app.radio[0].set_value("SQL proposal").run()
    next(b for b in app.button if b.label == "Ask").click().run()
    assert not app.exception and "SUM(amount)" in app.code[0].value


def failed(self, method, path, **kwargs):
    raise httpx.ConnectError("private transport details")


with patch.object(httpx.Client, "request", failed):
    # Reuse the app after a successful SQL query; a new failure must not
    # present stale SQL or a stale answer as the current response.
    app.text_area[0].input("A different question?").run()
    next(b for b in app.button if b.label == "Ask").click().run()
    assert not app.exception and "unavailable" in app.error[0].value
    assert "private" not in app.error[0].value
    assert not app.code
    assert "last_result" not in app.session_state
    assert not any("Returns accepted" in m.value for m in app.markdown)
print(
    "UI runtime: initial state, document answer/citation, SQL proposal and safe failure passed"
)

# AppTest does not expose a file-uploader control. Supply uploaded bytes at that
# widget boundary while exercising the real sidebar handlers and HTTP failures.
for action in ("Ingest document", "Ingest website"):
    for failure in (403, 422, 503, "unavailable"):
        current = {"failure": None}
        report = {"status": "completed", "chunk_count": 3, "job_id": "previous-job"}

        def ingest_response(self, method, path, **kwargs):
            expected_path = "/v1/admin/upload" if action == "Ingest document" else "/v1/admin/website"
            assert method == "POST" and path == expected_path
            if current["failure"] == "unavailable":
                raise httpx.ConnectError("private transport details")
            return httpx.Response(
                current["failure"] or 200,
                json=report if current["failure"] is None else {"detail": "private details"},
                request=httpx.Request(method, "http://test" + path),
            )

        uploaded = SimpleNamespace(name="guide.txt", getvalue=lambda: b"A guide.")
        with patch("streamlit.file_uploader", return_value=uploaded), patch.object(
            httpx.Client, "request", ingest_response
        ):
            ingestion_app = AppTest.from_file(
                os.getenv("UI_APP_PATH", str(Path(__file__).resolve().parents[1] / "unibot_RAG/streamlit_chatbot.py"))
            ).run()
            for field in ingestion_app.text_input:
                field.input({
                    "Administrator token": "test-only-admin",
                    "Source ID": "guide",
                    "Website URL": "https://example.com/guide",
                }[field.label])
            ingestion_app.run()
            next(b for b in ingestion_app.button if b.label == action).click().run()
            assert not ingestion_app.exception
            assert ingestion_app.session_state["ingestion_report"] == report
            assert any("Status: completed" in m.value for m in ingestion_app.markdown)
            assert ingestion_app.code[0].value == "previous-job"
            current["failure"] = failure
            next(b for b in ingestion_app.button if b.label == action).click().run()
            assert not ingestion_app.exception
            assert ingestion_app.error and "private" not in ingestion_app.error[0].value
            assert "ingestion_report" not in ingestion_app.session_state
            assert not ingestion_app.code
            assert not any("Status: completed" in m.value for m in ingestion_app.markdown)
            assert not any("Chunks: 3" in m.value for m in ingestion_app.markdown)
            current["failure"] = None
            report = {"status": "completed", "chunk_count": 1, "job_id": "new-job"}
            next(b for b in ingestion_app.button if b.label == action).click().run()
            assert not ingestion_app.exception and not ingestion_app.error
            assert ingestion_app.session_state["ingestion_report"] == report
            assert ingestion_app.code[0].value == "new-job"
print("UI runtime: repeated document/website ingestion failures clear stale reports")
