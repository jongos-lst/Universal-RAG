import os
from pathlib import Path
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
