from typing import TypedDict, List, Dict, Any
from apps.backend.core.models import ToolResult


class GraphState(TypedDict, total=False):
    run_id: str
    request_id: str
    user_query: str
    sku: str
    matrix_id: str
    test_id: str
    zeus_test_url: str
    event_callback: Any

    raw_log: str
    fetch_meta: Dict[str, Any]
    intent: Dict[str, Any]
    validation: Dict[str, Any]
    parsed: Dict[str, Any]
    core_plan: Dict[str, Any]
    expert_cycle: Dict[str, Any]

    tool_results: List[ToolResult]
    latest_tool_results: List[ToolResult]
    judge_result: Dict[str, Any]
    retry_count: int
    max_retry_count: int
    debug_trace: List[Dict[str, Any]]
    final_summary: str
    draft_summary: str
