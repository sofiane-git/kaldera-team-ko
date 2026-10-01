"""L'app Gradio se construit sans erreur, et ses callbacks (fonctions Python nues, appelables
sans passer par le runtime Gradio) se comportent correctement — y compris le respect du
garde-fou de coût par la callback « vrai LLM »."""

from __future__ import annotations

import pytest

gr = pytest.importorskip("gradio")

from kaldera.webapp import app as webapp_app  # noqa: E402


def test_build_app_returns_a_blocks_instance():
    demo = webapp_app.build_app()
    assert isinstance(demo, gr.Blocks)


def test_on_run_deterministic_returns_a_summary_dict():
    result = webapp_app.on_run_deterministic("sujet", ["RESEARCH", "FINALIZE"])
    assert result["status"] == "done"


def test_on_run_deterministic_reorders_steps_clicked_out_of_order():
    # Gradio's CheckboxGroup appends a re-checked box at the end of the value list, in click
    # order, not in the order the boxes are displayed — so a demo click sequence can legitimately
    # produce ["FINALIZE", "RESEARCH"] even though the form still shows RESEARCH above FINALIZE.
    result = webapp_app.on_run_deterministic("sujet", ["FINALIZE", "RESEARCH"])
    assert result["status"] == "done"
    assert result["stop_reason"] is None


def test_on_run_live_reorders_steps_before_calling_stream_live(monkeypatch):
    received: dict = {}

    def fake_stream_live(topic, steps, llm=None, max_steps=None):
        received["steps"] = steps
        yield {
            "node": "researcher",
            "status": "done",
            "step_count": 1,
            "artifacts": {},
            "stop_reason": None,
            "log": [],
        }

    monkeypatch.setattr(webapp_app.runners, "stream_live", fake_stream_live)
    list(webapp_app.on_run_live("sujet", ["FINALIZE", "RESEARCH"]))

    assert received["steps"] == ["RESEARCH", "FINALIZE"]


def test_format_live_chunk_shows_the_cooldown_message_when_present():
    chunk = {
        "node": None,
        "status": "aborted",
        "step_count": 0,
        "stop_reason": "cooldown",
        "message": "Patiente encore 10.0s avant un nouveau vrai run.",
    }
    assert "Patiente encore 10.0s" in webapp_app._format_live_chunk(chunk)


def test_on_run_guardrail_returns_the_expected_stop_reason():
    result = webapp_app.on_run_guardrail("budget_exceeded")
    assert result["stop_reason"] == "budget_exceeded"


def test_on_run_live_respects_the_cost_guard(monkeypatch):
    calls = {"n": 0}

    def fake_stream_live(topic, steps, llm=None, max_steps=None):
        calls["n"] += 1
        yield {
            "node": "researcher",
            "status": "done",
            "step_count": 1,
            "artifacts": {},
            "stop_reason": None,
            "log": [],
        }

    monkeypatch.setattr(webapp_app.runners, "stream_live", fake_stream_live)
    webapp_app._cost_guard._last_call = None  # état propre entre tests

    first_output = list(webapp_app.on_run_live("sujet", ["RESEARCH"]))
    assert calls["n"] == 1
    assert first_output  # au moins un chunk streamé

    second_output = list(webapp_app.on_run_live("sujet", ["RESEARCH"]))
    assert calls["n"] == 1  # pas de second appel réel : le garde-fou de coût a bloqué
    assert second_output[0]["stop_reason"] == "cooldown"


@pytest.mark.parametrize(
    ("env", "host", "port"),
    [
        ({}, "127.0.0.1", 7860),
        ({"GRADIO_SERVER_NAME": "0.0.0.0", "GRADIO_SERVER_PORT": "7999"}, "0.0.0.0", 7999),
    ],
    ids=["local_par_defaut", "conteneur"],
)
def test_main_listens_on_a_browsable_address_by_default(monkeypatch, env, host, port):
    # 0.0.0.0 n'est pas ouvrable dans un navigateur (ERR_ADDRESS_INVALID) : en local, l'app écoute
    # sur 127.0.0.1 ; seul le conteneur (Dockerfile.web) demande 0.0.0.0.
    for key in ("GRADIO_SERVER_NAME", "GRADIO_SERVER_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    launched: dict = {}

    class _FakeDemo:
        def launch(self, **kwargs):
            launched.update(kwargs)

    monkeypatch.setattr(webapp_app, "build_app", lambda: _FakeDemo())
    webapp_app.main()
    assert launched == {"server_name": host, "server_port": port}


def test_deterministic_ui_streams_one_view_per_frame():
    outputs = list(webapp_app._run_deterministic_ui("sujet", ["RESEARCH", "FINALIZE"], 0.0))
    assert len(outputs) >= 8  # vérification, 2 × (confie, écrit, accepte), fin, résumé
    assert all('id="active"' in view for view, _, _ in outputs)
    assert "statut : done" in outputs[-1][1]
