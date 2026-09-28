"""Entry point for the scheduled Databricks Job: load settings from a Databricks secret scope, then run one cycle.

On Databricks there is no agent/.env. Every setting lives in the secret scope instead (see scripts/deploy_databricks.py),
and the job's own identity authenticates to the Lakehouse.
"""

import base64
import os
from collections.abc import MutableMapping, Sequence

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

DEFAULT_SECRET_SCOPE = "returnguard"

SETTING_KEYS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "DATABRICKS_HOST",
    "DATABRICKS_WAREHOUSE_ID",
    "DATABRICKS_CATALOG",
    "DATABRICKS_SCHEMA",
    "DATABRICKS_SOURCE_SCHEMA",
    "BLOOMREACH_API_BASE_URL",
    "BLOOMREACH_PROJECT_TOKEN",
    "BLOOMREACH_API_KEY_ID",
    "BLOOMREACH_API_SECRET",
    "BLOOMREACH_CUSTOMER_ID_TYPE",
    "SHOPIFY_STORE_DOMAIN",
    "SHOPIFY_CLIENT_ID",
    "SHOPIFY_CLIENT_SECRET",
    "SHOPIFY_API_VERSION",
)


def load_settings_from_scope(client: WorkspaceClient, scope: str, target: MutableMapping[str, str]) -> list[str]:
    """Copy each setting from the secret scope into `target` unless already set. Returns the keys not found."""
    missing = []
    for key in SETTING_KEYS:
        if target.get(key):
            continue
        try:
            secret = client.secrets.get_secret(scope=scope, key=key)
        except NotFound:
            missing.append(key)
            continue
        target[key] = base64.b64decode(secret.value).decode("utf-8")
    return missing


def main(
    argv: Sequence[str] | None = None,
    client: WorkspaceClient | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    scope = env.get("RETURNGUARD_SECRET_SCOPE", DEFAULT_SECRET_SCOPE)
    missing = load_settings_from_scope(client or WorkspaceClient(), scope, env)
    if missing:
        print(f"returnguard: secret scope '{scope}' has no value for {', '.join(missing)}", flush=True)

    from returnguard.__main__ import main as cli_main

    return cli_main(list(argv) if argv is not None else ["run"])
