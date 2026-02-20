# Jupiter (Zeus log + Dify RAG)

## 1) Quickstart
1. cp .env.example .env
2. Fill:
   - ZEUS_TEST_URL_TEMPLATE
   - ZEUS_COOKIE (copy from browser)
   - DIFY_BASE_URL + DIFY_SPEC_APP_KEY + DIFY_TP_APP_KEY + DIFY_JIRA_APP_KEY
   - OPENAI_API_KEY / BASE_URL / MODEL

3. Run:
   docker-compose up --build

4. Open:
- Backend Swagger: http://localhost:8000/docs
- Streamlit: http://localhost:8502

## 2) How to get ZEUS_COOKIE
- Open Zeus test page in browser (already logged in)
- DevTools -> Network -> any request -> Request Headers -> copy the whole `Cookie:` value
- Paste into `.env` as ZEUS_COOKIE=...

If Zeus portal doesn't allow direct `{test_url}/logsarchive.zip`, edit:
`apps/backend/tools/zeus_portal.py -> resolve_zip_url()`

## 3) Runtime flow (CoreAgent orchestration)
1. `FetchAgent` 下载日志（Zeus zip）并兜底 mock。
2. `LogParser` 把 raw log 结构化为 `errors/warnings/highlights/tokens`。
3. `CoreAgent.plan` 决定是否调用下属专家（`spec/tp/jira`）以及轮次建议。
4. 专家 agent 按计划并行执行，并各自调用 Dify RAG（支持多轮重试）。
5. `CoreAgent.finalize` 汇总：解析线索 + 专家证据 -> 最终中文报告。
