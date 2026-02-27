from typing import TypedDict, List, Dict, Any
from apps.backend.core.models import ToolResult


class GraphState(TypedDict, total=False):
    request_id: str
    user_query: str
    sku: str
    matrix_id: str
    test_id: str
    zeus_test_url: str

    raw_log: str
    fetch_meta: Dict[str, Any]
    parsed: Dict[str, Any]
    core_plan: Dict[str, Any]

    tool_results: List[ToolResult]
    final_summary: str
    draft_summary: str
