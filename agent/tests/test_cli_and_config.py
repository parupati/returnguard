import json
from types import SimpleNamespace

import pytest

from conftest import FakeModel, make_decision
from returnguard.__main__ import main
from returnguard.agent import OrderOutcome, RunReport
from returnguard.config import DEFAULT_GEMINI_MODEL, ConfigError, load_settings
from returnguard.lakehouse import LakehouseError


def test_settings_require_api_key():
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_settings({"GEMINI_API_KEY": "  "})


def test_settings_default_and_custom_model():
    assert load_settings({"GEMINI_API_KEY": "k"}).gemini_model == DEFAULT_GEMINI_MODEL
    assert load_settings({"GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-x"}).gemini_model == "gemini-x"


def test_decide_prints_decision(context_path, capsys):
    exit_code = main(["decide", str(context_path)], model=FakeModel(make_decision().model_dump_json()))

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["decision"]["intervention_type"] == "exchange_offer"
    assert output["policy_adjustments"] == []


def test_decide_reports_missing_file(tmp_path, capsys):
    exit_code = main(["decide", str(tmp_path / "missing.json")], model=FakeModel("{}"))
    assert exit_code == 1
    assert "returnguard:" in capsys.readouterr().err


def test_decide_reports_missing_api_key(context_path, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    exit_code = main(["decide", str(context_path)])
    assert exit_code == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err


REPORT = RunReport(resolved=("#1: kept",), orders=(OrderOutcome("#2", "decided", "high risk"),))


def test_run_prints_report(capsys):
    agent = SimpleNamespace(run_once=lambda: REPORT)
    assert main(["run"], agent_factory=lambda: agent) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["resolved_outcomes"] == ["#1: kept"]
    assert output["orders"][0] == {"order": "#2", "status": "decided", "detail": "high risk"}


def test_run_reports_agent_errors(capsys):
    def boom():
        raise LakehouseError("warehouse offline")

    assert main(["run"], agent_factory=lambda: SimpleNamespace(run_once=boom)) == 1
    assert "warehouse offline" in capsys.readouterr().err


def test_watch_runs_cycles_sleeps_between_and_survives_failures(capsys):
    results = iter([LakehouseError("blip"), REPORT])
    sleeps = []

    def run_once():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    agent = SimpleNamespace(run_once=run_once)
    exit_code = main(["watch", "--interval", "5", "--cycles", "2"], agent_factory=lambda: agent, sleep=sleeps.append)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert sleeps == [5.0]
    assert "cycle 1 failed" in captured.err
    assert "#1: kept" in captured.out
