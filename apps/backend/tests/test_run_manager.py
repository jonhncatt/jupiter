import pytest

from apps.backend.services.run_manager import RunManager

pytestmark = pytest.mark.asyncio


async def test_run_manager_lifecycle():
    mgr = RunManager()
    run_id = await mgr.create_run({"request_id": "r1"})
    await mgr.set_status(run_id, "running")
    await mgr.append_event(run_id, {"type": "node.started", "payload": {"node": "fetch"}})
    await mgr.finish(run_id, {"ok": True})

    run = await mgr.get_run(run_id)
    assert run is not None
    assert run["status"] == "finished"
    assert run["done"] is True
    assert run["result"]["ok"] is True
    assert len(run["events"]) >= 2
