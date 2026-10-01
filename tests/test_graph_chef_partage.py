"""Le chemin « live » (graph.py) passe par le même chef que le chemin déterministe.

Réception, relance unique, annulation d'un passage refusé et journal du chef doivent y être
identiques. Faux LLM : aucun appel réseau.
"""

from __future__ import annotations

import kaldera.graph as graph_module
from kaldera.agents.researcher import Researcher
from kaldera.agents.writer import Writer
from kaldera.orchestrator import AGENTS_BY_NAME, SUPERVISOR
from kaldera.runner import run_scenario
from kaldera.state import TeamState
from kaldera.steps import Step
from kaldera.webapp import runners

ALL = [Step.RESEARCH, Step.DRAFT, Step.REVIEW, Step.FINALIZE]


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, prompt: str) -> _Reply:
        self.calls += 1
        return _Reply(f"réponse-{self.calls}")


def _live(steps, limit=10, agents=None, monkeypatch=None):
    if agents:
        team = dict(AGENTS_BY_NAME)
        team.update(agents)
        monkeypatch.setattr(graph_module, "AGENTS_BY_NAME", team)
    state = TeamState(topic="sujet", required_steps=list(steps))
    result = graph_module.build_graph(_FakeLLM(), limit).invoke(state, {"recursion_limit": 100})
    return TeamState(**result) if isinstance(result, dict) else result


def _chief_journal(state):
    return [
        (e["message"].split(" :")[0].split(" ")[0], e["step"])
        for e in state.log
        if e["agent_id"] == SUPERVISOR and not e["message"].startswith("limite")
    ]


def test_live_journal_matches_the_deterministic_chief():
    deterministic = run_scenario(
        {}, initial_state=TeamState(topic="sujet", required_steps=list(ALL))
    )
    live = _live(ALL)
    assert live.status == deterministic.status == "done"
    assert _chief_journal(live) == _chief_journal(deterministic)
    assert [e["agent_id"] for e in live.log if e["agent_id"] != SUPERVISOR] == [
        "researcher",
        "writer",
        "reviewer",
        "finalizer",
    ]


class _StuckLiveResearcher(Researcher):
    """Répond sans rien écrire, même avec un vrai LLM : refusé à chaque passage."""

    def __init__(self) -> None:
        self.calls = 0

    def act_with_llm(self, state, step, llm):
        self.calls += 1


def test_live_path_retries_once_then_stops(monkeypatch):
    stuck = _StuckLiveResearcher()
    state = _live(
        [Step.RESEARCH, Step.FINALIZE], agents={"researcher": stuck}, monkeypatch=monkeypatch
    )
    assert (state.status, state.stop_reason) == ("aborted", "reception_refused")
    assert stuck.calls == 2 and state.step_count == 2
    assert any(e["message"].startswith("réception refusée") for e in state.log)


class _IntruderLiveWriter(Writer):
    def act_with_llm(self, state, step, llm):
        super().act_with_llm(state, step, llm)
        state.artifacts["review"] = "intrus"


def test_live_path_rolls_back_a_refused_pass(monkeypatch):
    state = _live(
        [Step.RESEARCH, Step.DRAFT, Step.FINALIZE],
        agents={"writer": _IntruderLiveWriter()},
        monkeypatch=monkeypatch,
    )
    assert (state.status, state.stop_reason) == ("aborted", "reception_refused")
    assert "review" not in state.artifacts and "draft" not in state.artifacts
    assert "research" in state.artifacts


class _FlakyLiveResearcher(Researcher):
    def __init__(self) -> None:
        self.calls = 0

    def act_with_llm(self, state, step, llm):
        self.calls += 1
        if self.calls > 1:
            super().act_with_llm(state, step, llm)


def test_live_path_accepts_the_retry(monkeypatch):
    flaky = _FlakyLiveResearcher()
    state = _live(
        [Step.RESEARCH, Step.FINALIZE], agents={"researcher": flaky}, monkeypatch=monkeypatch
    )
    assert state.status == "done" and state.step_count == 3 and flaky.calls == 2


def test_live_step_limit_reached_through_retries(monkeypatch):
    state = _live(
        [Step.RESEARCH, Step.FINALIZE],
        limit=2,
        agents={"researcher": _FlakyLiveResearcher()},
        monkeypatch=monkeypatch,
    )
    assert (state.status, state.stop_reason) == ("aborted", "step_limit_reached")


def test_stream_live_reports_the_supervisor_stop(monkeypatch):
    team = dict(AGENTS_BY_NAME)
    team["researcher"] = _FlakyLiveResearcher()
    monkeypatch.setattr(graph_module, "AGENTS_BY_NAME", team)
    chunks = list(
        runners.stream_live("sujet", ["RESEARCH", "FINALIZE"], llm=_FakeLLM(), max_steps=2)
    )
    assert chunks[-1]["status"] == "aborted"
    assert chunks[-1]["stop_reason"] == "step_limit_reached"  # et non missing_closure
    assert chunks[-1]["node"] is None


def test_stream_live_carries_the_chief_journal():
    chunks = list(
        runners.stream_live("sujet", ["RESEARCH", "FINALIZE"], llm=_FakeLLM(), max_steps=5)
    )
    messages = [e["message"] for e in chunks[-1]["log"]]
    assert "confie RESEARCH à researcher" in messages
    assert "réception acceptée : FINALIZE" in messages
