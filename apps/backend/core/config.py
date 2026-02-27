from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI-compatible (for final summarization)
    openai_api_key: str = Field(default="CHANGE_ME", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    officetool_ca_cert_path: str = Field(default="", alias="OFFICETOOL_CA_CERT_PATH")
    offciatool_ca_cert_path: str = Field(default="", alias="OFFCIATOOL_CA_CERT_PATH")

    # Zeus portal downloading
    zeus_test_url_template: str = Field(
        default="",
        alias="ZEUS_TEST_URL_TEMPLATE",
        description="e.g. https://zeus.xxx.com/{sku}/test/{matrix_id}/{test_id}",
    )
    zeus_sku_default: str = Field(default="", alias="ZEUS_SKU_DEFAULT")
    zeus_log_zip_name: str = Field(default="logsarchive.zip", alias="ZEUS_LOG_ZIP_NAME")
    zeus_cookie: str = Field(default="", alias="ZEUS_COOKIE")
    zeus_extra_headers_json: str = Field(default="", alias="ZEUS_EXTRA_HEADERS_JSON")

    # Dify RAG
    dify_base_url: str = Field(default="", alias="DIFY_BASE_URL")  # should include /v1 or not, we normalize
    dify_mode: str = Field(default="chat", alias="DIFY_MODE")  # chat | workflow
    dify_spec_app_key: str = Field(default="", alias="DIFY_SPEC_APP_KEY")
    dify_tp_app_key: str = Field(default="", alias="DIFY_TP_APP_KEY")
    dify_jira_app_key: str = Field(default="", alias="DIFY_JIRA_APP_KEY")

    # Cache
    cache_ttl_seconds: int = Field(default=600, alias="CACHE_TTL_SECONDS")


settings = Settings()
