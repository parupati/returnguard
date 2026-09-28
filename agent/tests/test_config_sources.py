import pytest

from returnguard.config import ConfigError, load_bloomreach_settings, load_databricks_settings

DATABRICKS_ENV = {
    "DATABRICKS_HOST": "https://dbc.example.com",
    "DATABRICKS_WAREHOUSE_ID": "wh",
    "DATABRICKS_CATALOG": "databricks-hackathon",
    "DATABRICKS_SCHEMA": "frontier",
    "DATABRICKS_SOURCE_SCHEMA": "00data",
}

BLOOMREACH_ENV = {
    "BLOOMREACH_API_BASE_URL": "https://api-engagement.bloomreach.com/",
    "BLOOMREACH_PROJECT_TOKEN": "tok",
    "BLOOMREACH_API_KEY_ID": "kid",
    "BLOOMREACH_API_SECRET": "sec",
}


def test_databricks_settings_load():
    settings = load_databricks_settings(DATABRICKS_ENV)
    assert settings.catalog == "databricks-hackathon"
    assert settings.source_schema == "00data"


def test_databricks_settings_report_all_missing_names():
    with pytest.raises(ConfigError, match="DATABRICKS_HOST, DATABRICKS_WAREHOUSE_ID"):
        load_databricks_settings({})


def test_databricks_settings_reject_unsafe_identifiers():
    with pytest.raises(ConfigError, match="DATABRICKS_SCHEMA"):
        load_databricks_settings({**DATABRICKS_ENV, "DATABRICKS_SCHEMA": "frontier`; DROP TABLE x"})


def test_bloomreach_settings_load_with_defaults():
    settings = load_bloomreach_settings(BLOOMREACH_ENV)
    assert settings.api_base_url == "https://api-engagement.bloomreach.com"
    assert settings.customer_id_type == "registered"


def test_bloomreach_settings_require_secret():
    with pytest.raises(ConfigError, match="BLOOMREACH_API_SECRET"):
        load_bloomreach_settings({**BLOOMREACH_ENV, "BLOOMREACH_API_SECRET": ""})
