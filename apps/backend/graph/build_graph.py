from langgraph.graph import StateGraph, END
from apps.backend.graph.state import GraphState


def build(node_fetch, node_parse, node_core, node_tools, node_summarize):
    g = StateGraph(GraphState)
    g.add_node("fetch", node_fetch)
    g.add_node("parse", node_parse)
    g.add_node("core", node_core)
    g.add_node("tools", node_tools)
    g.add_node("summarize", node_summarize)

    g.set_entry_point("fetch")
    g.add_edge("fetch", "parse")
    g.add_edge("parse", "core")
    g.add_edge("core", "tools")
    g.add_edge("tools", "summarize")
    g.add_edge("summarize", END)
    return g.compile()
