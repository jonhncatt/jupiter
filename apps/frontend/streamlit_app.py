import os
import time
import asyncio
import queue
import threading
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Dict

import requests
import streamlit as st
from dotenv import load_dotenv

from apps.backend.core.models import AnalyzeRequest, AnalyzeResponse
from apps.backend.services.cache import TTLCache
from jupiter_core.workflow import run_analysis

# Load project .env for local runs (docker env vars still take precedence).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)

BACKEND = os.getenv("JUPITER_BACKEND", "http://127.0.0.1:8000")
UI_MODE = os.getenv("JUPITER_UI_MODE", "api").strip().lower()
_LOCAL_CACHE = TTLCache(ttl_seconds=600)


def backend_candidates(raw: str) -> list[str]:
    vals = [x.strip().rstrip("/") for x in (raw or "").split(",") if x.strip()]
    if not vals:
        vals = ["http://127.0.0.1:8000"]
    has_compose_host = any(urlparse(v).hostname == "backend" for v in vals)
    if has_compose_host:
        for fallback in ("http://127.0.0.1:8000", "http://localhost:8000"):
            if fallback not in vals:
                vals.append(fallback)
    return vals


BACKEND_CANDIDATES = backend_candidates(BACKEND)


def api_request_json(method: str, path: str, *, payload: Dict[str, Any] | None = None, timeout: int = 30) -> tuple[Dict[str, Any], str]:
    errs: list[str] = []
    for base in BACKEND_CANDIDATES:
        url = f"{base}{path}"
        try:
            resp = requests.request(method, url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json(), base
        except Exception as e:
            errs.append(f"{base}: {e}")
    raise RuntimeError(" ; ".join(errs))

st.set_page_config(page_title="Jupiter", layout="wide")
st.title("Jupiter - Multi-Agent Log Analysis")
st.caption(f"UI mode: `{UI_MODE}` | backend candidates: `{', '.join(BACKEND_CANDIDATES)}`")

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
show_debug_detail = st.checkbox("显示每一步详细数据（调试）", value=True)


def render_result(data: Dict[str, Any]) -> None:
    raw = data.get("raw") or {}
    tool_results = data.get("tool_results", [])
    fetch_meta = (data.get("raw") or {}).get("fetch_meta") or {}
    if fetch_meta:
        st.subheader("Fetch 状态")
        st.write(
            f"- source={fetch_meta.get('source')} | reason={fetch_meta.get('reason')} | files_count={fetch_meta.get('files_count', 0)}"
        )
        if fetch_meta.get("test_url"):
            st.write(f"- test_url: {fetch_meta.get('test_url')}")
        if fetch_meta.get("zip_url"):
            st.write(f"- zip_url: {fetch_meta.get('zip_url')}")
        if fetch_meta.get("downloaded_zip_path"):
            st.write(f"- downloaded_zip_path: {fetch_meta.get('downloaded_zip_path')}")
        if fetch_meta.get("status_code") is not None:
            st.write(f"- status_code: {fetch_meta.get('status_code')}")
        if fetch_meta.get("final_url"):
            st.write(f"- final_url: {fetch_meta.get('final_url')}")
        if fetch_meta.get("has_cookie_header") is not None:
            st.write(f"- has_cookie_header: {fetch_meta.get('has_cookie_header')}")
        if fetch_meta.get("extract_status"):
            st.write(f"- extract_status: {fetch_meta.get('extract_status')}")
        if fetch_meta.get("zip_member_count") is not None:
            st.write(f"- zip_member_count: {fetch_meta.get('zip_member_count')}")
        if fetch_meta.get("zip_members_preview"):
            st.write(f"- zip_members_preview: {fetch_meta.get('zip_members_preview')}")
        if fetch_meta.get("top_files"):
            st.write(f"- top_files: {fetch_meta.get('top_files')}")
        if show_debug_detail:
            with st.expander("Fetch 内部步骤", expanded=False):
                st.json(fetch_meta.get("steps", []))
            with st.expander("Fetch Meta 全量", expanded=False):
                st.json(fetch_meta)

    if show_debug_detail:
        st.subheader("执行步骤总览")
        step_rows = [
            {
                "step": "intent",
                "status": "ok" if raw.get("intent") else "empty",
                "detail": (raw.get("intent") or {}).get("source", ""),
            },
            {
                "step": "validate",
                "status": "ok" if (raw.get("validation") or {}).get("valid") else "warn",
                "detail": ",".join((raw.get("validation") or {}).get("errors", []))
                or ",".join((raw.get("validation") or {}).get("warnings", []))
                or ((raw.get("validation") or {}).get("resolved") or {}).get("effective_source")
                or "ok",
            },
            {
                "step": "fetch",
                "status": fetch_meta.get("reason", ""),
                "detail": fetch_meta.get("test_url") or fetch_meta.get("zip_url") or "",
            },
            {
                "step": "parse",
                "status": "ok" if raw.get("parsed") else "empty",
                "detail": f"errors={len((raw.get('parsed') or {}).get('errors', []))}, warnings={len((raw.get('parsed') or {}).get('warnings', []))}",
            },
            {
                "step": "plan",
                "status": "ok" if raw.get("core_plan") else "empty",
                "detail": str((raw.get("core_plan") or {}).get("selected_tools", [])),
            },
            {
                "step": "experts",
                "status": "ok" if tool_results else "empty",
                "detail": ", ".join(f"{tr.get('tool')}:{tr.get('ok')}" for tr in tool_results),
            },
            {
                "step": "finalize",
                "status": "ok" if data.get("overall_summary") else "empty",
                "detail": data.get("overall_summary", "")[:120],
            },
        ]
        st.table(step_rows)

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

    if show_debug_detail:
        st.subheader("步骤细节（Debug）")
        with st.expander("Intent 解析", expanded=False):
            st.json(raw.get("intent", {}))
        with st.expander("参数校验", expanded=False):
            st.json(raw.get("validation", {}))
        with st.expander("Core 路由决策", expanded=False):
            st.json(raw.get("core_plan", {}))
        with st.expander("Parser 输出", expanded=False):
            parsed = raw.get("parsed", {})
            st.write(f"- errors: {len(parsed.get('errors', []))}")
            st.write(f"- warnings: {len(parsed.get('warnings', []))}")
            st.write(f"- highlights: {len(parsed.get('highlights', []))}")
            st.write(f"- tokens: {parsed.get('tokens', {})}")
            st.write("sample errors:")
            for line in parsed.get("errors", [])[:10]:
                st.write(f"- {line}")
            st.write("sample highlights:")
            for line in parsed.get("highlights", [])[:10]:
                st.write(f"- {line}")
        with st.expander("Raw Log 预览", expanded=False):
            raw_log = raw.get("raw_log", "")
            st.code(raw_log[:6000] if raw_log else "(empty raw_log)")
        with st.expander("Graph Trace", expanded=False):
            st.json(raw.get("debug_trace", []))
        with st.expander("专家交互细节", expanded=False):
            expert_debug = [
                {
                    "tool": tr.get("tool"),
                    "ok": tr.get("ok"),
                    "summary": tr.get("summary"),
                    "debug": tr.get("debug", {}),
                }
                for tr in tool_results
            ]
            st.json(expert_debug)
        with st.expander("完整 Raw 输出", expanded=False):
            st.json(raw)


def event_to_line(evt: Dict[str, Any]) -> str:
    seq = evt.get("seq")
    typ = evt.get("type")
    payload = evt.get("payload") or {}
    target = payload.get("agent") or payload.get("node") or "-"
    status = payload.get("status") or ("ok" if payload.get("ok") is True else ("fail" if payload.get("ok") is False else "-"))
    info = payload.get("summary") or payload.get("reason") or payload.get("error") or ""
    icon = {
        "started": "...",
        "ok": "OK",
        "warn": "WARN",
        "error": "ERR",
        "fail": "ERR",
    }.get(str(status).lower(), "--")
    return f"[{seq}] {icon:<4} {typ:<16} target={target:<20} status={status:<8} {info}"


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


def run_local(payload: Dict[str, Any], timeline_box) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
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
    return result.model_dump(mode="json"), events


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
            data, local_events = run_local(payload, timeline_box)
        except Exception as e:
            st.error(f"本地模式运行失败: {e}")
            st.stop()
        render_result(data)
        if show_debug_detail:
            with st.expander("事件明细（local）", expanded=False):
                st.json(local_events)
    elif use_run_api:
        try:
            run, chosen_backend = api_request_json("POST", "/api/runs", payload=payload, timeout=30)
        except Exception as e:
            st.error(f"启动运行失败: {e}")
            st.stop()

        run_id = run["run_id"]
        st.info(f"run_id: {run_id} | backend: {chosen_backend}")
        status_box = st.empty()
        timeline_box = st.empty()
        event_lines: list[str] = []
        event_details: list[Dict[str, Any]] = []
        seen_seq = 0
        result: Dict[str, Any] | None = None

        for _ in range(360):  # up to ~6 minutes
            try:
                rr = requests.get(f"{chosen_backend}/api/runs/{run_id}", timeout=30)
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
                event_details.append(evt)
            timeline_box.code("\n".join(event_lines[-120:]) if event_lines else "等待事件...")

            if state.get("done"):
                if state.get("error"):
                    st.error(f"运行失败: {state['error']}")
                    st.info("请检查并重新输入日志路径、matrix_id/test_id 或 Zeus URL，然后再次提交。")
                    st.stop()
                result = state.get("result")
                break
            time.sleep(1)

        if not result:
            st.error("运行超时，未拿到最终结果。")
            st.stop()

        render_result(result)
        if show_debug_detail:
            with st.expander("事件明细（api/runs）", expanded=False):
                st.json(event_details)
    else:
        try:
            data, _ = api_request_json("POST", "/api/analyze", payload=payload, timeout=180)
        except Exception as e:
            st.error(f"调用后端失败: {e}")
            st.stop()
        render_result(data)
