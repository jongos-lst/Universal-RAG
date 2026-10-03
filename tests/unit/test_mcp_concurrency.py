import asyncio
import threading

import pytest

from unibot_RAG.mcp_server import create_server


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["search_knowledge", "answer_question"])
async def test_blocking_tools_run_off_event_loop(name):
    event_thread = threading.get_ident()
    called_threads = []

    class Service:
        def search(self, *args):
            called_threads.append(threading.get_ident())
            return []

        def answer(self, *args):
            called_threads.append(threading.get_ident())
            return {"answer": "ok"}

    await create_server(Service()).call_tool(name, {"question": "policy?"})
    assert called_threads and called_threads[0] != event_thread


@pytest.mark.asyncio
async def test_pending_search_does_not_block_other_requests_or_cancellation():
    entered = threading.Event()
    release = threading.Event()

    class Service:
        def search(self, *args):
            entered.set()
            # A deadlock guard, not the expected completion path.
            assert release.wait(timeout=2)
            return []

        def answer(self, *args):
            return {"answer": "available"}

    server = create_server(Service())
    pending = asyncio.create_task(server.call_tool("search_knowledge", {"question": "slow"}))
    try:
        async with asyncio.timeout(0.5):
            while not entered.is_set():
                await asyncio.sleep(0.001)
            await server.call_tool("answer_question", {"question": "fast"})
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_mcp_cancel_scope_does_not_wait_for_blocking_worker():
    import anyio

    release = threading.Event()
    entered = threading.Event()

    class Service:
        def search(self, *args):
            entered.set()
            assert release.wait(timeout=2)
            return []

    try:
        with pytest.raises(TimeoutError):
            with anyio.fail_after(0.1):
                await create_server(Service()).call_tool("search_knowledge", {"question": "slow"})
        assert entered.is_set()
        assert not release.is_set()
    finally:
        release.set()
