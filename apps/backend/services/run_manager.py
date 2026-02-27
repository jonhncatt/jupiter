import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional


class RunManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._runs: Dict[str, Dict[str, Any]] = {}

    async def create_run(self, request_payload: Dict[str, Any]) -> str:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = time.time()
        async with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "status": "queued",
                "created_at": now,
                "updated_at": now,
                "done": False,
                "error": None,
                "request": request_payload,
                "result": None,
                "events": [],
                "event_seq": 0,
            }
        await self.append_event(
            run_id,
            {
                "type": "run.created",
                "payload": {"request_id": request_payload.get("request_id")},
            },
        )
        return run_id

    async def set_status(self, run_id: str, status: str) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            run["status"] = status
            run["updated_at"] = time.time()

    async def append_event(self, run_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            run["event_seq"] += 1
            run["updated_at"] = time.time()
            run["events"].append(
                {
                    "seq": run["event_seq"],
                    "timestamp": run["updated_at"],
                    "run_id": run_id,
                    **event,
                }
            )

    async def finish(self, run_id: str, result_payload: Dict[str, Any]) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            run["status"] = "finished"
            run["done"] = True
            run["result"] = result_payload
            run["updated_at"] = time.time()
        await self.append_event(run_id, {"type": "run.finished", "payload": {"ok": True}})

    async def fail(self, run_id: str, error: str) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            run["status"] = "failed"
            run["done"] = True
            run["error"] = error
            run["updated_at"] = time.time()
        await self.append_event(run_id, {"type": "run.failed", "payload": {"error": error[:500]}})

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            # Shallow-copy + list copy to avoid exposing internal mutable references.
            return {
                **run,
                "events": list(run["events"]),
            }

    async def list_events(self, run_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return []
            return [e for e in run["events"] if int(e.get("seq", 0)) > after_seq]
