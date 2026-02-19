from langgraph.graph import StateGraph, END
from apps.backend.graph.state import GraphState


def build(node_fetch, node_parse, node_core_plan, node_experts, node_finalize):
    g = StateGraph(GraphState)
    g.add_node("fetch", node_fetch)
    g.add_node("parse", node_parse)
    g.add_node("core_plan", node_core_plan)
    g.add_node("experts", node_experts)
    g.add_node("finalize", node_finalize)

    g.set_entry_point("fetch")
    g.add_edge("fetch", "parse")
    g.add_edge("parse", "core_plan")
    g.add_edge("core_plan", "experts")
    g.add_edge("experts", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
