"""GUI Gradio : 3 onglets (Exécuter / Casser un garde-fou / Comparer). Un seul opérateur en
projection (pas d'auth, pas d'isolation de session — décidé au brainstorming du 30/09/2026)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import gradio as gr  # type: ignore[import-untyped]

from ..orchestrator import STEP_TO_ARTIFACT
from ..steps import Step
from . import artifacts_view, flow_view, runners
from .broken_registries import DEFECTS
from .cost_guard import CostGuard

STEPS_CHOICES = ["RESEARCH", "DRAFT", "REVIEW", "FINALIZE"]
GUARDRAIL_LABELS = {
    "role_violation": "Rôle hors périmètre",
    "budget_exceeded": "Budget de tokens dépassé",
    "step_limit": "Limite d'étapes atteinte",
    "stuck_agent": "Agent bloqué (ne progresse pas)",
}

_cost_guard = CostGuard()


def _canonical_order(steps: list[str]) -> list[str]:
    # `gr.CheckboxGroup` renvoie les valeurs cochées dans l'ordre des clics, pas dans l'ordre
    # d'affichage des cases : une re-coche après décoche peut légitimement produire
    # ["FINALIZE", "RESEARCH"] alors que le formulaire affiche toujours RESEARCH avant FINALIZE.
    return [s for s in STEPS_CHOICES if s in steps]


def on_run_deterministic(topic: str, steps: list[str]) -> dict:
    return runners.run_deterministic(topic, _canonical_order(steps))


def on_run_scenario(scenario_id: str) -> dict:
    return runners.run_named_scenario(scenario_id)


def on_run_guardrail(defect: str) -> dict:
    return runners.run_guardrail(defect)


def on_run_live(topic: str, steps: list[str]) -> Iterator[dict]:
    if not _cost_guard.try_acquire():
        wait = round(_cost_guard.seconds_remaining(), 1)
        yield {
            "node": None,
            "status": "aborted",
            "step_count": 0,
            "artifacts": {},
            "stop_reason": "cooldown",
            "log": [],
            "message": f"Patiente encore {wait}s avant un nouveau vrai run.",
        }
        return
    yield from runners.stream_live(topic, _canonical_order(steps))


def _format_summary(result: dict) -> str:
    lines = [f"statut : {result['status']}", f"étapes : {result['step_count']}"]
    if result.get("stop_reason"):
        lines.append(f"stop_reason : {result['stop_reason']}")
    return "\n".join(lines)


def _format_live_chunk(chunk: dict) -> str:
    node = chunk.get("node") or "—"
    parts = [f"[{node}] statut={chunk['status']} étapes={chunk['step_count']}"]
    if chunk.get("stop_reason"):
        parts.append(f"stop_reason={chunk['stop_reason']}")
    if chunk.get("message"):
        parts.append(chunk["message"])
    return " ".join(parts)


def _expected_artifacts(steps: list[str]) -> list[str]:
    """Artefacts que la demande produira, pour n'afficher que les fiches utiles."""
    return [STEP_TO_ARTIFACT[Step(s)] for s in steps if s in Step.__members__]


def _authors(frame: flow_view.Frame | None) -> dict[str, str]:
    return {key: author for key, (author, _) in frame.store.items()} if frame else {}


def _cards_for_frame(frame: flow_view.Frame, expected: list[str] | None) -> str:
    writing = frame.artifact if frame.kind in ("work", "reject_work") else None
    return artifacts_view.render_artifacts_html(
        {key: value for key, (_, value) in frame.store.items()},
        _authors(frame),
        writing=writing if writing not in frame.store else None,
        expected=expected,
    )


def _animate(
    result: dict, topic: str, delay: float, expected: list[str] | None = None
) -> Iterator[tuple[str, str, str]]:
    """Rejoue une exécution image par image : schéma animé, déroulé et fiches d'artefacts."""
    frames = flow_view.frames_from_log(
        result["log"], result["artifacts"], topic, result["status"], result.get("stop_reason")
    )
    for index, frame in enumerate(frames):
        lines = [f"{i}. {f.text}" for i, f in enumerate(frames[: index + 1], 1)]
        yield (
            flow_view.render_flow_html(frame, frames[: index + 1], topic),
            "\n".join(lines),
            _cards_for_frame(frame, expected),
        )
        if delay > 0 and index < len(frames) - 1:
            time.sleep(delay)
    lines = [f"{i}. {f.text}" for i, f in enumerate(frames, 1)]
    last = frames[-1] if frames else None
    final_html = flow_view.render_flow_html(last, frames, topic)
    cards = artifacts_view.render_artifacts_html(
        result["artifacts"], _authors(last), expected=expected
    )
    yield final_html, _format_summary(result) + "\n\n" + "\n".join(lines), cards


def _run_deterministic_ui(topic: str, steps: list[str], delay: float = 0.0):
    expected = _expected_artifacts(_canonical_order(steps))
    yield from _animate(on_run_deterministic(topic, steps), topic, delay, expected)


def _run_scenario_ui(scenario_id: str, delay: float = 0.0):
    scenario = {s["id"]: s for s in runners.load_scenarios()}.get(scenario_id, {})
    context = scenario.get("initial_context", {})
    expected = _expected_artifacts(context.get("required_steps", []))
    yield from _animate(on_run_scenario(scenario_id), context.get("topic", ""), delay, expected)


def _run_live_ui(topic: str, steps: list[str]):
    log_lines: list[str] = []
    artifacts: dict = {}
    chunks: list[dict] = []
    expected = _expected_artifacts(_canonical_order(steps))
    for chunk in on_run_live(topic, steps):
        log_lines.append(_format_live_chunk(chunk))
        artifacts = chunk.get("artifacts", artifacts)
        chunks.append(chunk)
        frames = flow_view.frames_from_live(chunks, topic)
        current = frames[-1] if frames else None
        cards = artifacts_view.render_artifacts_html(
            artifacts, _authors(current), expected=expected
        )
        yield flow_view.render_flow_html(current, frames, topic), "\n".join(log_lines), cards


def _run_guardrail_ui(defect: str, delay: float = 0.0):
    result = on_run_guardrail(defect)
    for html_view, lines, _ in _animate(result, "démo garde-fou", delay):
        yield html_view, lines


def _compare_deterministic_ui(topic: str, steps: list[str]) -> tuple[str, str]:
    result = on_run_deterministic(topic, steps)
    expected = _expected_artifacts(_canonical_order(steps))
    return _format_summary(result), artifacts_view.render_artifacts_html(
        result["artifacts"], expected=expected
    )


def _compare_live_ui(topic: str, steps: list[str]):
    for _, lines, artifacts in _run_live_ui(topic, steps):
        yield lines, artifacts


def _guardrail_handler(defect: str):
    def handler(delay: float):
        yield from _run_guardrail_ui(defect, delay)

    return handler


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Kaldera — démo") as demo:
        gr.Markdown("# Kaldera — orchestration multi-agents, en direct")

        with gr.Tab("Exécuter"):
            flow_html = gr.HTML(flow_view.render_flow_html(None), label="Architecture en direct")
            speed = gr.Slider(0.0, 2.0, value=0.8, step=0.1, label="Vitesse : secondes par étape")
            topic_box = gr.Textbox(label="Sujet", value="lancement produit")
            steps_box = gr.CheckboxGroup(choices=STEPS_CHOICES, value=STEPS_CHOICES, label="Étapes")
            with gr.Row():
                det_button = gr.Button("Lancer (déterministe)")
                live_button = gr.Button("Lancer (vrai LLM)")

            scenario_ids = [s["id"] for s in runners.load_scenarios()]
            with gr.Row():
                scenario_dropdown = gr.Dropdown(
                    choices=scenario_ids,
                    value=scenario_ids[0] if scenario_ids else None,
                    label="Scénario prédéfini (scenarios/scenarios_test.json)",
                )
                scenario_button = gr.Button("Lancer le scénario")

            output_log = gr.Textbox(label="Déroulé", lines=10)
            output_artifacts = gr.HTML(
                artifacts_view.render_artifacts_html(None), label="Artefacts"
            )

            run_outputs = [flow_html, output_log, output_artifacts]
            det_button.click(_run_deterministic_ui, [topic_box, steps_box, speed], run_outputs)
            live_button.click(_run_live_ui, [topic_box, steps_box], run_outputs)
            scenario_button.click(_run_scenario_ui, [scenario_dropdown, speed], run_outputs)

        with gr.Tab("Casser un garde-fou"):
            gr.Markdown("Toujours déterministe : gratuit, instantané, rejouable à l'infini.")
            guardrail_flow = gr.HTML(flow_view.render_flow_html(None), label="Où le flux casse")
            guardrail_speed = gr.Slider(
                0.0, 2.0, value=0.8, step=0.1, label="Vitesse : secondes par étape"
            )
            guardrail_output = gr.Textbox(label="Résultat", lines=12)
            for defect in DEFECTS:
                button = gr.Button(GUARDRAIL_LABELS[defect])
                button.click(
                    _guardrail_handler(defect),
                    inputs=guardrail_speed,
                    outputs=[guardrail_flow, guardrail_output],
                )

        with gr.Tab("Comparer"):
            cmp_topic = gr.Textbox(label="Sujet", value="lancement produit")
            cmp_steps = gr.CheckboxGroup(choices=STEPS_CHOICES, value=STEPS_CHOICES, label="Étapes")
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Déterministe")
                    cmp_det_button = gr.Button("Lancer")
                    cmp_det_output = gr.Textbox(label="Déroulé", lines=10)
                    cmp_det_artifacts = gr.HTML(
                        artifacts_view.render_artifacts_html(None), label="Artefacts"
                    )
                with gr.Column():
                    gr.Markdown("### Vrai LLM")
                    cmp_live_button = gr.Button("Lancer")
                    cmp_live_output = gr.Textbox(label="Déroulé", lines=10)
                    cmp_live_artifacts = gr.HTML(
                        artifacts_view.render_artifacts_html(None), label="Artefacts"
                    )

            cmp_det_button.click(
                _compare_deterministic_ui,
                [cmp_topic, cmp_steps],
                [cmp_det_output, cmp_det_artifacts],
            )
            cmp_live_button.click(
                _compare_live_ui, [cmp_topic, cmp_steps], [cmp_live_output, cmp_live_artifacts]
            )

    return demo


def main() -> None:
    # En local : 127.0.0.1, adresse qu'un navigateur sait ouvrir (http://localhost:7860), et
    # interface non exposée au réseau. Le conteneur (Dockerfile.web) fixe GRADIO_SERVER_NAME=0.0.0.0
    # pour être joignable depuis l'extérieur ; 0.0.0.0 n'est pas une adresse ouvrable dans un
    # navigateur (ERR_ADDRESS_INVALID).
    host = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1")
    port = int(os.environ.get("GRADIO_SERVER_PORT", "7860"))
    print(f"Kaldera : ouvre http://localhost:{port} dans ton navigateur.", flush=True)
    build_app().launch(server_name=host, server_port=port)


if __name__ == "__main__":
    main()
