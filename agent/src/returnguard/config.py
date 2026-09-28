import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_BLOOMREACH_ID_TYPE = "registered"

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_\-]+$")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str


@dataclass(frozen=True)
class DatabricksSettings:
    host: str
    warehouse_id: str
    catalog: str
    schema: str
    source_schema: str


@dataclass(frozen=True)
class BloomreachSettings:
    api_base_url: str
    project_token: str
    api_key_id: str
    api_secret: str
    customer_id_type: str


@dataclass(frozen=True)
class ShopifySettings:
    store_domain: str
    client_id: str
    client_secret: str
    api_version: str


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _require(source: Mapping[str, str], *names: str) -> dict[str, str]:
    values = {name: source.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError(f"Missing settings in agent/.env: {', '.join(missing)}")
    return values


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = _env(env)
    api_key = source.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in.")
    model = source.get("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
    return Settings(gemini_api_key=api_key, gemini_model=model)


def load_databricks_settings(env: Mapping[str, str] | None = None) -> DatabricksSettings:
    values = _require(
        _env(env),
        "DATABRICKS_HOST",
        "DATABRICKS_WAREHOUSE_ID",
        "DATABRICKS_CATALOG",
        "DATABRICKS_SCHEMA",
        "DATABRICKS_SOURCE_SCHEMA",
    )
    for name in ("DATABRICKS_CATALOG", "DATABRICKS_SCHEMA", "DATABRICKS_SOURCE_SCHEMA"):
        if not _SQL_IDENTIFIER.match(values[name]):
            raise ConfigError(f"{name} may only contain letters, digits, '_' and '-': {values[name]!r}")
    return DatabricksSettings(
        host=values["DATABRICKS_HOST"],
        warehouse_id=values["DATABRICKS_WAREHOUSE_ID"],
        catalog=values["DATABRICKS_CATALOG"],
        schema=values["DATABRICKS_SCHEMA"],
        source_schema=values["DATABRICKS_SOURCE_SCHEMA"],
    )


def load_shopify_settings(env: Mapping[str, str] | None = None) -> ShopifySettings:
    values = _require(
        _env(env),
        "SHOPIFY_STORE_DOMAIN",
        "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET",
        "SHOPIFY_API_VERSION",
    )
    domain = values["SHOPIFY_STORE_DOMAIN"].removeprefix("https://").rstrip("/")
    if not domain.endswith(".myshopify.com"):
        raise ConfigError(f"SHOPIFY_STORE_DOMAIN must be a *.myshopify.com domain: {domain!r}")
    return ShopifySettings(
        store_domain=domain,
        client_id=values["SHOPIFY_CLIENT_ID"],
        client_secret=values["SHOPIFY_CLIENT_SECRET"],
        api_version=values["SHOPIFY_API_VERSION"],
    )


def load_bloomreach_settings(env: Mapping[str, str] | None = None) -> BloomreachSettings:
    source = _env(env)
    values = _require(
        source,
        "BLOOMREACH_API_BASE_URL",
        "BLOOMREACH_PROJECT_TOKEN",
        "BLOOMREACH_API_KEY_ID",
        "BLOOMREACH_API_SECRET",
    )
    return BloomreachSettings(
        api_base_url=values["BLOOMREACH_API_BASE_URL"].rstrip("/"),
        project_token=values["BLOOMREACH_PROJECT_TOKEN"],
        api_key_id=values["BLOOMREACH_API_KEY_ID"],
        api_secret=values["BLOOMREACH_API_SECRET"],
        customer_id_type=source.get("BLOOMREACH_CUSTOMER_ID_TYPE", "").strip() or DEFAULT_BLOOMREACH_ID_TYPE,
    )
