# Jupiter (Zeus log + Dify RAG)

## 1) Quickstart
1. cp .env.example .env
2. Fill:
   - ZEUS_TEST_URL_TEMPLATE
   - ZEUS_COOKIE (copy from browser)
   - DIFY_BASE_URL + DIFY_SPEC_APP_KEY + DIFY_TP_APP_KEY
   - OPENAI_API_KEY / BASE_URL / MODEL

3. Run:
   docker-compose up --build

4. Open:
- Backend Swagger: http://localhost:8000/docs
- Streamlit: http://localhost:8501

## 2) How to get ZEUS_COOKIE
- Open Zeus test page in browser (already logged in)
- DevTools -> Network -> any request -> Request Headers -> copy the whole `Cookie:` value
- Paste into `.env` as ZEUS_COOKIE=...

If Zeus portal doesn't allow direct `{test_url}/logsarchive.zip`, edit:
`apps/backend/tools/zeus_portal.py -> resolve_zip_url()`
