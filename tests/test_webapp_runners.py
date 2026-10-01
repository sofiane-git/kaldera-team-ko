"""Fonctions pures (sans Gradio) qui enveloppent run_scenario/build_graph pour la GUI."""

from __future__ import annotations

from kaldera.webapp import runners


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, fail_on: int | None = None) -> None:
        self.calls = 0
        self.fail_on = fail_on

    def invoke(self, prompt: str) -> _FakeResponse:
        self.calls += 1
        if self.fail_on is not None and self.calls == self.fail_on:
            raise RuntimeError("panne réseau simulée")
        return _FakeResponse(f"fake-{self.calls}")


def test_run_deterministic_happy_path():
    result = runners.run_deterministic(
        "lancement produit", ["RESEARCH", "DRAFT", "REVIEW", "FINALIZE"]
    )
    assert result["status"] == "done"
    assert result["step_count"] == 4
    assert sorted(result["artifacts"]) == ["draft", "final", "research", "review"]
    assert result["stop_reason"] is None


def test_run_deterministic_empty_topic_is_refused_not_raised():
    result = runners.run_deterministic("", ["RESEARCH"])
    assert result["status"] == "aborted"
    assert result["stop_reason"] == "invalid_demand:empty"


def test_run_deterministic_empty_steps_is_refused_not_raised():
    result = runners.run_deterministic("sujet valide", [])
    assert result["status"] == "aborted"
    assert result["stop_reason"] == "invalid_demand:empty"


def test_run_deterministic_duplicate_steps_is_refused_not_raised():
    result = runners.run_deterministic("sujet", ["RESEARCH", "RESEARCH", "FINALIZE"])
    assert result["status"] == "aborted"
    assert result["stop_reason"] == "invalid_demand:duplicate_step"


def test_stream_live_yields_one_chunk_per_step():
    fake = _FakeLLM()
    chunks = list(runners.stream_live("sujet", ["RESEARCH", "FINALIZE"], llm=fake, max_steps=5))

    assert len(chunks) == 2
    assert chunks[0]["node"] == "researcher"
    assert chunks[-1]["node"] == "finalizer"
    assert chunks[-1]["status"] == "done"
    assert sorted(chunks[-1]["artifacts"]) == ["final", "research"]


def test_stream_live_invalid_demand_yields_single_refusal_chunk():
    fake = _FakeLLM()
    chunks = list(runners.stream_live("", [], llm=fake))

    assert len(chunks) == 1
    assert chunks[0]["node"] is None
    assert chunks[0]["status"] == "aborted"
    assert chunks[0]["stop_reason"].startswith("invalid_demand:")
    assert fake.calls == 0


def test_stream_live_llm_failure_yields_llm_error_instead_of_raising():
    fake = _FakeLLM(fail_on=1)
    chunks = list(runners.stream_live("sujet", ["RESEARCH", "FINALIZE"], llm=fake, max_steps=5))

    assert chunks[-1]["status"] == "aborted"
    assert chunks[-1]["stop_reason"] == "llm_error"


def test_stream_live_credential_error_before_streaming_yields_llm_error(monkeypatch):
    def _raise():
        raise RuntimeError("variables d'environnement manquantes")

    monkeypatch.setattr(runners, "build_llm", _raise)
    chunks = list(runners.stream_live("sujet", ["RESEARCH"], max_steps=5))

    assert len(chunks) == 1
    assert chunks[0]["status"] == "aborted"
    assert chunks[0]["stop_reason"] == "llm_error"


def test_stream_live_missing_finalize_is_reported_not_silently_pending():
    fake = _FakeLLM()
    chunks = list(runners.stream_live("sujet", ["RESEARCH"], llm=fake, max_steps=5))

    assert chunks[-1]["status"] == "aborted"
    assert chunks[-1]["stop_reason"] == "missing_closure"


def test_run_guardrail_role_violation():
    result = runners.run_guardrail("role_violation")
    assert result["status"] == "aborted"
    assert result["stop_reason"] == "role_violation"


def test_run_guardrail_step_limit():
    result = runners.run_guardrail("step_limit")
    assert result["status"] == "aborted"
    assert result["stop_reason"] == "step_limit_reached"
