from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class AnalyzeRequest(BaseModel):
    request_id: str = Field(default="req-001")
    user_query: str
    sku: Optional[str] = None
    matrix_id: Optional[str] = None
    test_id: Optional[str] = None
    # 允许以后扩展：直接给完整链接/本地路径
    zeus_test_url: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    source: str
    snippet: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool: str
    ok: bool
    summary: str
    evidences: List[Evidence] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    request_id: str
    overall_summary: str
    suspected_root_causes: List[str]
    key_evidences: List[Evidence]
    tool_results: List[ToolResult]
    recommendations: List[str]
    next_actions: List[str]
    raw: Dict[str, Any] = Field(default_factory=dict)
