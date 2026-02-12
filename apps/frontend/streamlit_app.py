import os
import requests
import streamlit as st

BACKEND = os.getenv("JUPITER_BACKEND", "http://backend:8000")

st.set_page_config(page_title="Jupiter", layout="wide")
st.title("Jupiter - Zeus Log + Dify RAG")

col1, col2 = st.columns(2)
with col1:
    matrix_id = st.text_input("matrix id", value="")
with col2:
    test_id = st.text_input("test id", value="")

user_query = st.text_area(
    "你的问题", height=120, value="这个 log 里 timeout waiting for controller ready 可能根因是什么？"
)
zeus_test_url = st.text_input("可选：直接填写 Zeus test URL（覆盖 matrix/test 拼接）", value="")

if st.button("分析"):
    payload = {
        "request_id": "req-streamlit-001",
        "user_query": user_query,
        "matrix_id": matrix_id or None,
        "test_id": test_id or None,
        "zeus_test_url": zeus_test_url or None,
        "context": {},
    }

    try:
        r = requests.post(f"{BACKEND}/api/analyze", json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.error(f"调用后端失败: {e}")
        st.stop()

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

    st.subheader("建议 / 下一步动作")
    for x in data.get("recommendations", []):
        st.write(f"- {x}")
    for x in data.get("next_actions", []):
        st.write(f"- {x}")
