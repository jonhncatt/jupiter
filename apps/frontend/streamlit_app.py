import os
import time
import asyncio
import queue
import threading
from typing import Any, Dict

import requests
import streamlit as st

from apps.backend.core.models import AnalyzeRequest, AnalyzeResponse
from apps.backend.services.cache import TTLCache
from jupiter_core.workflow import run_analysis

BACKEND = os.getenv("JUPITER_BACKEND", "http://backend:8000")
UI_MODE = os.getenv("JUPITER_UI_MODE", "api").strip().lower()
_LOCAL_CACHE = TTLCache(ttl_seconds=600)

st.set_page_config(page_title="Jupiter", layout="wide")
st.title("Jupiter - Multi-Agent Log Analysis")
st.caption(f"UI mode: `{UI_MODE}`")

col1, col2, col3 = st.columns(3)
with col1:
    sku = st.text_input("sku", value="")
with col2:
    matrix_id = st.text_input("matrix id", value="")
with col3:
    test_id = st.text_input("test id", value="")

user_query = st.text_area(
    "你的问题",
    height=120,
    value="这个 log 里 timeout waiting for controller ready 可能根因是什么？",
)
zeus_test_url = st.text_input("可选：直接填写 Zeus test URL/本地目录路径（覆盖 sku/matrix/test 拼接）", value="")
use_run_api = st.checkbox("实时显示多Agent轨迹（推荐）", value=True)


def render_result(data: Dict[str, Any]) -> None:
    st.subheader("总体结论")
    st.write(data["overall_summary"])

    st.subheader("可疑根因")
    for x in data.get("suspected_root_causes", []):
        st.write(f"- {x}")

    st.subheader("关键证据")
    for ev in data.get("key_evidences", []):
        st.write(f"- [{ev['source']}] {ev['snippet']}")

    st.subheader("工具结果")
    for tr in data.get("tool_results", []):
        with st.expander(f"{tr['tool']} ok={tr['ok']} - {tr['summary']}"):
            for ev in tr.get("evidences", []):
                st.write(f"* [{ev['source']}] {ev['snippet']}")
            if tr.get("debug"):
                st.caption("debug")
                st.json(tr["debug"])

    st.subheader("建议 / 下一步动作")
    for x in data.get("recommendations", []):
        st.write(f"- {x}")
    for x in data.get("next_actions", []):
        st.write(f"- {x}")

    with st.expander("调试数据（raw）", expanded=False):
        st.json(data.get("raw", {}))


def event_to_line(evt: Dict[str, Any]) -> str:
    seq = evt.get("seq")
    typ = evt.get("type")
    payload = evt.get("payload") or {}
    target = payload.get("agent") or payload.get("node") or "-"
    status = payload.get("status") or ("ok" if payload.get("ok") is True else ("fail" if payload.get("ok") is False else "-"))
    info = payload.get("summary") or payload.get("reason") or payload.get("error") or ""
    return f"[{seq}] {typ:<16} target={target:<20} status={status:<8} {info}"


def run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put((True, asyncio.run(coro)))
        except Exception as e:
            result_queue.put((False, e))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    ok, payload = result_queue.get()
    if ok:
        return payload
    raise payload


def run_local(payload: Dict[str, Any], timeline_box) -> Dict[str, Any]:
    req = AnalyzeRequest(**payload)
    events: list[Dict[str, Any]] = []
    event_lines: list[str] = []

    def _collector(evt: Dict[str, Any]) -> None:
        events.append(evt)
        event_lines.append(event_to_line({"seq": len(events), **evt}))
        timeline_box.code("\n".join(event_lines[-120:]))

    result: AnalyzeResponse = run_async(
        run_analysis(
            req,
            use_cache=False,
            run_id="local-ui",
            event_callback=_collector,
            cache=_LOCAL_CACHE,
        )
    )
    return result.model_dump(mode="json")


if st.button("分析"):
    payload = {
        "request_id": "req-streamlit-001",
        "user_query": user_query,
        "sku": sku or None,
        "matrix_id": matrix_id or None,
        "test_id": test_id or None,
        "zeus_test_url": zeus_test_url or None,
        "context": {},
    }

    if UI_MODE == "local":
        if use_run_api:
            st.info("当前为 local 模式：直接调用 jupiter_core，不经过 /api/runs。")
        timeline_box = st.empty()
        timeline_box.code("local workflow running...")
        try:
            data = run_local(payload, timeline_box)
        except Exception as e:
            st.error(f"本地模式运行失败: {e}")
            st.stop()
        render_result(data)
    elif use_run_api:
        try:
            r = requests.post(f"{BACKEND}/api/runs", json=payload, timeout=30)
            r.raise_for_status()
            run = r.json()
        except Exception as e:
            st.error(f"启动运行失败: {e}")
            st.stop()

        run_id = run["run_id"]
        st.info(f"run_id: {run_id}")
        status_box = st.empty()
        timeline_box = st.empty()
        event_lines: list[str] = []
        seen_seq = 0
        result: Dict[str, Any] | None = None

        for _ in range(360):  # up to ~6 minutes
            try:
                rr = requests.get(f"{BACKEND}/api/runs/{run_id}", timeout=30)
                rr.raise_for_status()
                state = rr.json()
            except Exception as e:
                status_box.error(f"轮询运行状态失败: {e}")
                st.stop()

            status_box.write(
                f"status={state.get('status')} | done={state.get('done')} | events={len(state.get('events', []))}"
            )

            new_events = [e for e in state.get("events", []) if int(e.get("seq", 0)) > seen_seq]
            for evt in new_events:
                seen_seq = max(seen_seq, int(evt.get("seq", 0)))
                event_lines.append(event_to_line(evt))
            timeline_box.code("\n".join(event_lines[-120:]) if event_lines else "等待事件...")

            if state.get("done"):
                if state.get("error"):
                    st.error(f"运行失败: {state['error']}")
                    st.stop()
                result = state.get("result")
                break
            time.sleep(1)

        if not result:
            st.error("运行超时，未拿到最终结果。")
            st.stop()

        render_result(result)
    else:
        try:
            r = requests.post(f"{BACKEND}/api/analyze", json=payload, timeout=180)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            st.error(f"调用后端失败: {e}")
            st.stop()
        render_result(data)
