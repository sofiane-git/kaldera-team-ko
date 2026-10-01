"""Le CLI garde son comportement par défaut (scénarios) et route `--live` vers `run_live`."""

from __future__ import annotations

import sys

import kaldera.graph
from kaldera import cli
from kaldera.state import TeamState


def test_live_flag_routes_to_run_live(monkeypatch, capsys):
    calls = {}

    def fake_run_live(topic, required_steps, max_steps=None):
        calls["args"] = (topic, required_steps)
        state = TeamState(topic=topic, status="done")
        state.artifacts["final"] = "contenu factice"
        return state

    monkeypatch.setattr(kaldera.graph, "run_live", fake_run_live)
    monkeypatch.setattr(
        sys, "argv", ["kaldera", "--live", "sujet test", "--steps", "RESEARCH,FINALIZE"]
    )

    cli.main()

    assert calls["args"] == ("sujet test", ["RESEARCH", "FINALIZE"])
    out = capsys.readouterr().out
    assert "status=done" in out
    assert "contenu factice" in out


def test_default_run_replays_provided_scenarios(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["kaldera"])

    cli.main()

    out = capsys.readouterr().out
    assert "[happy_path]" in out
    assert "[research_only]" in out
