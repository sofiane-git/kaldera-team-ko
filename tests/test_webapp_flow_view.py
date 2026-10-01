"""Vue animée de l'architecture : les images suivent le journal, le SVG est sûr et bien formé."""

import xml.etree.ElementTree as ET

import pytest

from kaldera.webapp import runners
from kaldera.webapp.flow_view import (
    frames_from_live,
    frames_from_log,
    render_flow_html,
    render_flow_svg,
)

ALL_STEPS = ["RESEARCH", "DRAFT", "REVIEW", "FINALIZE"]


def _frames(result, topic="sujet"):
    return frames_from_log(
        result["log"], result["artifacts"], topic, result["status"], result["stop_reason"]
    )


def test_happy_path_frames_follow_the_journal():
    frames = _frames(runners.run_deterministic("sujet", ALL_STEPS))
    assert [f.kind for f in frames] == ["check"] + ["delegate", "work", "accept"] * 4 + ["end"]
    delegated = [f.agent for f in frames if f.kind == "delegate"]
    assert delegated == ["researcher", "writer", "reviewer", "finalizer"]
    written = [f.artifact for f in frames if f.kind == "work"]
    assert written == ["research", "draft", "review", "final"]
    assert frames[-1].status == "done"
    assert set(frames[-1].store) == {"research", "draft", "review", "final"}
    assert frames[-1].store["review"][0] == "reviewer"


def test_artifact_appears_in_the_store_only_once_accepted():
    frames = _frames(runners.run_deterministic("sujet", ["RESEARCH", "FINALIZE"]))
    work = next(f for f in frames if f.kind == "work" and f.artifact == "research")
    accept = next(f for f in frames if f.kind == "accept" and f.step == "RESEARCH")
    assert "research" not in work.store
    assert accept.store["research"] == ("researcher", "research:sujet")


def test_refusal_then_retry_then_stop_is_shown():
    frames = _frames(runners.run_guardrail("stuck_agent"))
    kinds = [f.kind for f in frames]
    assert kinds == [
        "check",
        "delegate",
        "reject_work",
        "refuse",
        "delegate",
        "reject_work",
        "stop",
    ]
    assert frames[-1].stop_reason == "reception_refused"
    assert "sans research conforme" in frames[2].text


@pytest.mark.parametrize(
    ("defect", "code"),
    [
        ("role_violation", "role_violation"),
        ("budget_exceeded", "budget_exceeded"),
        ("step_limit", "step_limit_reached"),
    ],
)
def test_each_guardrail_ends_on_its_stop_code(defect, code):
    frames = _frames(runners.run_guardrail(defect))
    assert frames[-1].kind == "stop" and frames[-1].stop_reason == code
    assert code in render_flow_svg(frames[-1])


def test_invalid_demand_shows_a_stop_without_delegation():
    frames = _frames(runners.run_deterministic("sujet", ["DRAFT", "FINALIZE"]))
    assert [f.kind for f in frames] == ["check", "stop"]
    assert frames[-1].stop_reason == "invalid_demand:missing_input"


def test_live_chunks_become_frames():
    chunks = [
        {
            "node": "researcher",
            "status": "pending",
            "artifacts": {"research": "r"},
            "log": [{"agent_id": "researcher", "step": "RESEARCH", "message": "a traité RESEARCH"}],
        },
        {
            "node": "finalizer",
            "status": "done",
            "artifacts": {"research": "r", "final": "f"},
            "log": [
                {"agent_id": "researcher", "step": "RESEARCH", "message": "a traité RESEARCH"},
                {"agent_id": "finalizer", "step": "FINALIZE", "message": "a traité FINALIZE"},
            ],
        },
    ]
    frames = frames_from_live(chunks, "sujet")
    assert [f.kind for f in frames] == ["check"] + ["delegate", "work", "accept"] * 2 + ["end"]
    assert frames[-1].store["final"] == ("finalizer", "f")


def test_user_text_is_escaped():
    hostile = '<script>alert("x")</script>'
    result = runners.run_deterministic(hostile, ["RESEARCH", "FINALIZE"])
    page = "".join(render_flow_html(f, [f], hostile) for f in _frames(result, hostile))
    assert "<script>" not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize("index", range(14))
def test_every_frame_renders_well_formed_svg(index):
    frames = _frames(runners.run_deterministic("sujet & co", ALL_STEPS))
    svg = render_flow_svg(frames[index], "sujet & co")
    ET.fromstring(svg)  # lève une erreur si le SVG est mal formé
    assert 'id="active"' in svg and "animateMotion" in svg


def test_empty_view_invites_to_run():
    page = render_flow_html(None)
    assert "Lance une exécution" in page
    ET.fromstring(render_flow_svg(None))
