import json
import logging
import re
from typing import Any, Dict, List

from apps.backend.core.config import settings
from apps.backend.core.models import ToolResult
from apps.backend.llm.openai_client import chat
from apps.backend.prompts.log_analysis_skill import CORE_AGENT_PLAYBOOK

logger = logging.getLogger(__name__)

SYSTEM_FINALIZE = """你是SSD测试日志分析的总控专家（Core Agent Finalizer）。
你会收到：
1) 用户问题
2) 日志解析结果
3) 核心路由决策（为何调用哪些专家）
4) 各专家返回证据

请输出结构化中文结果：
1. 总结（2-5句）
2. 可能根因（<=3条，按可能性排序）
3. 关键证据（引用原文片段）
4. 建议（可执行）
5. 下一步动作（补充信息与复现方案）
要求：证据导向，避免空话；若信息不足明确指出缺口。"""

SYSTEM_PLAN = """你是SSD测试日志分析的总控规划器（Core Agent Planner）。
你需要决定：
1) 是否需要调用 spec / tp / jira expert
2) 为什么调用
3) 给每个 expert 下发什么定制任务

只输出 JSON：
{
  "selected_tools": ["spec", "tp", "jira"],
  "reason": "string",
  "round_hint": 1,
  "expert_queries": {
    "spec": "string",
    "tp": "string",
    "jira": "string"
  }
}

约束：
- selected_tools 只能使用 spec/tp/jira
- 如果用户明确要求只总结，则 selected_tools 必须为空
- 不要把用户原始问题原封不动复制给所有 expert
- expert_queries 必须是针对各 expert 的具体任务
- 只返回 JSON，不要额外文本"""


class CoreAgent:
    """
    Core coordinator:
    - Analyze parsed log + user query
    - Decide which downstream agents should run
    """

    name = "core_agent(orchestrator)"

    async def plan(self, query: str, parsed: Dict[str, Any], raw_log: str = "") -> Dict[str, Any]:
        rules_plan = self._rules_plan(query, parsed, raw_log=raw_log)
        if not self._llm_available():
            rules_plan["planner_source"] = "rules"
            return rules_plan

        llm_plan = self._llm_plan(query, parsed, rules_plan)
        if llm_plan is None:
            rules_plan["planner_source"] = "rules_fallback"
            return rules_plan
        return llm_plan

    def _rules_plan(self, query: str, parsed: Dict[str, Any], raw_log: str = "") -> Dict[str, Any]:
        q = (query or "").lower()
        tokens = (parsed or {}).get("tokens") or {}
        highlights = (parsed or {}).get("highlights") or []
        domain = (parsed or {}).get("domain_context") or {}
        pcb = domain.get("pcb_console") or {}
        nvmecore = domain.get("nvmecore") or {}

        selected_tools: List[str] = []
        reasons: List[str] = []

        wants_summary_only = _is_summary_only(q)

        needs_spec = any(
            k in q
            for k in [
                "spec",
                "规范",
                "协议",
                "nvme",
                "apst",
                "csts",
                "rdy",
                "timeout",
                "寄存器",
            ]
        ) or bool(tokens.get("mentions_apst") or tokens.get("mentions_csts_rdy") or tokens.get("mentions_timeout"))

        needs_tp = any(
            k in q
            for k in [
                "tp",
                "code",
                "代码",
                "函数",
                "实现",
                "cpp",
                "c++",
                "source",
                "header",
                ".h",
                ".cpp",
            ]
        ) or bool(
            re.search(r"\b(function|module|driver|path)\b", q)
        ) or bool(tokens.get("pcb_has_script_line") or pcb.get("script_line"))

        needs_jira = any(k in q for k in ["jira", "ticket", "issue", "缺陷", "单号"])
        needs_jira = needs_jira or any(k in q for k in ["之前", "类似", "以前", "历史", "怎么处理", "是否发生过"])

        if pcb.get("status") in {"fail", "skip"}:
            reasons.append(
                "PCB_TESTLOG_CONSOLE_OUTPUT.txt 显示失败/跳过状态，优先结合脚本行号与测试名分析。"
            )
            if "tp" not in selected_tools:
                selected_tools.append("tp")

        if nvmecore.get("command_lines"):
            reasons.append("nvmecore_log.txt 尾部存在命令/回复记录，可交给 Spec expert 解读。")
            if "spec" not in selected_tools:
                selected_tools.append("spec")

        if not wants_summary_only:
            if needs_spec:
                if "spec" not in selected_tools:
                    selected_tools.append("spec")
                reasons.append("问题或日志包含规范/协议相关线索，需查Spec RAG。")
            if needs_tp:
                if "tp" not in selected_tools:
                    selected_tools.append("tp")
                reasons.append("问题涉及代码实现或函数路径，需查TP RAG。")
            if needs_jira:
                if "jira" not in selected_tools:
                    selected_tools.append("jira")
                reasons.append("用户想查历史类似问题/处理方式，尝试Jira知识库。")

        # If no explicit route but log has significant error signals, do a minimal RAG route.
        if not selected_tools and not wants_summary_only and highlights:
            selected_tools = ["spec", "tp"]
            reasons.append("存在错误高亮但无明确路由指令，默认拉起Spec+TP做交叉验证。")

        if wants_summary_only:
            reasons.append("用户请求仅总结，跳过RAG子agent。")

        expert_queries = self._build_expert_queries(
            original_query=query,
            parsed=parsed,
            selected_tools=selected_tools,
        )

        return {
            "selected_tools": selected_tools,
            "reason": " ".join(reasons) if reasons else "未触发子agent，直接进入总结。",
            "core_playbook": CORE_AGENT_PLAYBOOK.strip(),
            "need_rag": bool(selected_tools),
            "round_hint": 2,  # downstream expert agents can use this as max rounds hint
            "expert_queries": expert_queries,
            "planner_source": "rules",
        }

    def _llm_plan(self, query: str, parsed: Dict[str, Any], rules_plan: Dict[str, Any]) -> Dict[str, Any] | None:
        user = self._build_llm_plan_input(query=query, parsed=parsed, rules_plan=rules_plan)
        try:
            temperature = settings.openai_plan_temperature or settings.openai_temperature or None
            raw = chat(SYSTEM_PLAN + "\n\n" + CORE_AGENT_PLAYBOOK.strip(), user, temperature=temperature)
        except Exception as e:
            logger.warning("Core planner LLM failed: %s", e)
            return None

        obj = _parse_json_object(raw)
        if not isinstance(obj, dict):
            logger.warning("Core planner LLM returned non-JSON: %s", (raw or "")[:300])
            return None

        selected_tools = _sanitize_tools(obj.get("selected_tools"))
        reason = str(obj.get("reason") or "").strip()
        round_hint = _sanitize_round_hint(obj.get("round_hint"))
        expert_queries = obj.get("expert_queries") if isinstance(obj.get("expert_queries"), dict) else {}

        if _is_summary_only((query or "").lower()) and selected_tools:
            # Respect explicit summary-only cases or hard rule skips.
            selected_tools = []

        merged_expert_queries = dict(rules_plan.get("expert_queries", {}))
        for tool in selected_tools:
            val = expert_queries.get(tool)
            if isinstance(val, str) and val.strip():
                merged_expert_queries[tool] = val.strip()
        # Ensure every selected tool has a concrete query.
        for tool in list(selected_tools):
            if not merged_expert_queries.get(tool):
                merged_expert_queries[tool] = rules_plan.get("expert_queries", {}).get(tool, "")
        if any(not merged_expert_queries.get(tool) for tool in selected_tools):
            logger.warning("Core planner LLM missing expert queries: %s", selected_tools)
            return None

        return {
            "selected_tools": selected_tools,
            "reason": reason or rules_plan.get("reason", ""),
            "core_playbook": CORE_AGENT_PLAYBOOK.strip(),
            "need_rag": bool(selected_tools),
            "round_hint": round_hint,
            "expert_queries": {tool: merged_expert_queries[tool] for tool in selected_tools},
            "planner_source": "llm",
            "planner_raw_preview": (raw or "")[:800],
            "rules_plan_fallback": {
                "selected_tools": rules_plan.get("selected_tools", []),
                "reason": rules_plan.get("reason", ""),
            },
        }

    def _build_llm_plan_input(self, *, query: str, parsed: Dict[str, Any], rules_plan: Dict[str, Any]) -> str:
        domain = parsed.get("domain_context") or {}
        pcb = domain.get("pcb_console") or {}
        nvmecore = domain.get("nvmecore") or {}
        lines: List[str] = []
        lines.append("【用户问题】")
        lines.append(query)
        lines.append("\n【规则基线建议】")
        lines.append(json.dumps(
            {
                "selected_tools": rules_plan.get("selected_tools", []),
                "reason": rules_plan.get("reason", ""),
                "expert_queries": rules_plan.get("expert_queries", {}),
            },
            ensure_ascii=False,
        ))
        lines.append("\n【Parser tokens】")
        lines.append(json.dumps(parsed.get("tokens", {}), ensure_ascii=False))
        lines.append("\n【关键高亮】")
        lines.extend((parsed.get("highlights") or [])[:12])
        lines.append("\n【PCB console】")
        lines.append(json.dumps(pcb, ensure_ascii=False))
        lines.append("\n【nvmecore】")
        lines.append(json.dumps({"command_lines": nvmecore.get("command_lines", [])[:12]}, ensure_ascii=False))
        return "\n".join(lines)

    def _llm_available(self) -> bool:
        key = (settings.openai_api_key or "").strip()
        return bool(key and key != "CHANGE_ME")

    def _build_expert_queries(
        self,
        *,
        original_query: str,
        parsed: Dict[str, Any],
        selected_tools: List[str],
    ) -> Dict[str, str]:
        domain = parsed.get("domain_context") or {}
        pcb = domain.get("pcb_console") or {}
        nvmecore = domain.get("nvmecore") or {}
        query = original_query.strip()
        out: Dict[str, str] = {}

        if "spec" in selected_tools:
            parts = [
                "你现在是 Spec Expert，请只回答规范/协议层面的问题。",
                f"用户原始问题：{query}",
            ]
            if pcb.get("status_line"):
                parts.append(f"PCB console状态行：{pcb.get('status_line')}")
            if nvmecore.get("command_lines"):
                parts.append("请结合以下 nvmecore 尾部命令/回复，解释命令含义、结果是否异常、可能对应的 NVMe 规范点：")
                parts.extend(nvmecore.get("command_lines", [])[:12])
            else:
                parts.append("请重点从规范角度解释当前失败现象。")
            out["spec"] = "\n".join(parts)

        if "tp" in selected_tools:
            parts = [
                "你现在是 TP Expert，请优先定位测试代码/脚本/函数路径。",
                f"用户原始问题：{query}",
            ]
            if pcb.get("status_line"):
                parts.append(f"PCB console状态行：{pcb.get('status_line')}")
            if pcb.get("script_line"):
                parts.append(
                    f"请优先定位与测试 `{pcb.get('test_name')}` Rev `{pcb.get('revision')}` 脚本行号 #{pcb.get('script_line')} 相关的测试代码、函数或路径。"
                )
            else:
                parts.append("请定位与当前失败最相关的测试实现、函数和代码路径。")
            out["tp"] = "\n".join(parts)

        if "jira" in selected_tools:
            parts = [
                "你现在是 Jira Expert，请专注查历史相似问题与处理方式。",
                f"用户原始问题：{query}",
                "请查找历史上是否有类似失败、之前如何处理、对应的缺陷单号和结论。",
            ]
            if pcb.get("status_line"):
                parts.append(f"失败摘要：{pcb.get('status_line')}")
            if nvmecore.get("command_lines"):
                parts.append("相关命令/返回：")
                parts.extend(nvmecore.get("command_lines", [])[:8])
            out["jira"] = "\n".join(parts)
        return out

    async def finalize(
        self,
        *,
        query: str,
        parsed: Dict[str, Any],
        core_plan: Dict[str, Any],
        expert_reports: List[ToolResult],
    ) -> str:
        lines: List[str] = []
        lines.append("【用户问题】")
        lines.append(query)

        lines.append("\n【核心路由决策】")
        lines.append(
            f"need_rag={core_plan.get('need_rag')} selected_tools={core_plan.get('selected_tools', [])}"
        )
        lines.append(f"planner_source={core_plan.get('planner_source', 'unknown')}")
        lines.append(f"reason={core_plan.get('reason', '')}")
        if core_plan.get("expert_queries"):
            lines.append("expert_queries=" + str(core_plan.get("expert_queries")))

        lines.append("\n【日志解析关键线索】")
        for item in (parsed.get("highlights") or [])[:25]:
            lines.append(f"- {item}")

        lines.append("\n【专家回馈】")
        for report in expert_reports:
            lines.append(f"- {report.tool} ok={report.ok}: {report.summary}")
            for ev in report.evidences[:4]:
                lines.append(f"  * ({ev.source}) {ev.snippet}")

        try:
            temperature = settings.openai_finalize_temperature or settings.openai_temperature or None
            return chat(SYSTEM_FINALIZE + "\n\n" + CORE_AGENT_PLAYBOOK.strip(), "\n".join(lines), temperature=temperature)
        except Exception as e:
            logger.warning("Core finalize failed: %s", e)
            return (
                "总结：信息不足，当前仅能基于有限日志与专家结果给出初步判断。\n"
                "可能根因：1) 控制器就绪超时相关时序问题 2) 低功耗/寄存器配置异常 3) 环境因素导致初始化失败。\n"
                "关键证据：请查看 highlights 与专家证据字段。\n"
                "建议：补充CSTS/CC/APST时序与复现环境差异数据。\n"
                "下一步动作：再次复现并抓取完整寄存器快照。"
            )

    # Backward-compatible alias
    async def run(self, query: str, parsed: Dict[str, Any]) -> Dict[str, Any]:
        return await self.plan(query, parsed)


def _parse_json_object(raw: str) -> Dict[str, Any] | None:
    if not raw:
        return None
    text = raw.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _sanitize_tools(value: Any) -> List[str]:
    allowed = {"spec", "tp", "jira"}
    out: List[str] = []
    if not isinstance(value, list):
        return out
    for item in value:
        tool = str(item).strip().lower()
        if tool in allowed and tool not in out:
            out.append(tool)
    return out


def _sanitize_round_hint(value: Any) -> int:
    try:
        num = int(value)
    except Exception:
        return 2
    return max(1, min(num, 3))


def _is_summary_only(q: str) -> bool:
    return any(k in q for k in ["只总结", "仅总结", "summary only", "no rag"])
