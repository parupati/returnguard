import base64
from types import SimpleNamespace

from databricks.sdk.errors import NotFound

from returnguard.jobs import SETTING_KEYS, load_settings_from_scope, main
from returnguard.lakehouse import workspace_client
from returnguard.config import DatabricksSettings


class FakeSecrets:
    def __init__(self, values):
        self.values = values
        self.requested = []

    def get_secret(self, scope, key):
        self.requested.append((scope, key))
        if key not in self.values:
            raise NotFound(f"{key} not found")
        return SimpleNamespace(value=base64.b64encode(self.values[key].encode()).decode())


def test_loads_every_setting_from_the_scope():
    secrets = FakeSecrets({key: f"value-{key}" for key in SETTING_KEYS})
    target = {}
    missing = load_settings_from_scope(SimpleNamespace(secrets=secrets), "returnguard", target)

    assert missing == []
    assert target["GEMINI_API_KEY"] == "value-GEMINI_API_KEY"
    assert {scope for scope, _ in secrets.requested} == {"returnguard"}


def test_existing_values_win_and_missing_keys_are_reported():
    secrets = FakeSecrets({"GEMINI_API_KEY": "from-scope"})
    target = {"GEMINI_MODEL": "already-set"}
    missing = load_settings_from_scope(SimpleNamespace(secrets=secrets), "returnguard", target)

    assert target["GEMINI_API_KEY"] == "from-scope"
    assert target["GEMINI_MODEL"] == "already-set"
    assert ("returnguard", "GEMINI_MODEL") not in secrets.requested
    assert "SHOPIFY_CLIENT_SECRET" in missing


def test_main_runs_one_cycle_with_scope_settings(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("returnguard.__main__.main", lambda argv: calls.append(argv) or 0)
    env = {"RETURNGUARD_SECRET_SCOPE": "custom"}
    secrets = FakeSecrets({"GEMINI_API_KEY": "k"})

    assert main(client=SimpleNamespace(secrets=secrets), environ=env) == 0
    assert calls == [["run"]]
    assert env["GEMINI_API_KEY"] == "k"
    assert secrets.requested[0][0] == "custom"
    assert "has no value for" in capsys.readouterr().out


SETTINGS = DatabricksSettings("https://dbc.example.com", "wh", "c", "s", "src")


def test_workspace_client_picks_identity(monkeypatch):
    seen = []
    monkeypatch.setattr("returnguard.lakehouse.WorkspaceClient", lambda **kwargs: seen.append(kwargs))

    workspace_client(SETTINGS, {"DATABRICKS_RUNTIME_VERSION": "16.4"})
    workspace_client(SETTINGS, {"DATABRICKS_CLIENT_ID": "sp", "DATABRICKS_CLIENT_SECRET": "x"})
    workspace_client(SETTINGS, {})

    assert seen == [
        {},
        {"host": "https://dbc.example.com"},
        {"host": "https://dbc.example.com", "auth_type": "external-browser"},
    ]
