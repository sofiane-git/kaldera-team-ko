"""Grille de preuve : réintroduit chaque défaut du diagnostic, un à la fois, et vérifie qu'un
test l'attrape.

Protocole (doc/conception_point_4_detection_par_les_tests.md, section 7) :
1. copier le dépôt dans un dossier temporaire (le dépôt lui-même n'est jamais modifié) ;
2. vérifier que la suite passe entièrement sans défaut (référence) ;
3. pour chaque défaut : l'injecter seul, relancer les tests, et exiger qu'au moins un des tests
   désignés échoue.

Usage, depuis la racine du dépôt :  uv run python scripts/grille_de_preuve.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COPIED = ("src", "tests", "scenarios", "specs", "pyproject.toml")


@dataclass
class Defect:
    label: str
    path: str
    old: str
    new: str
    expected: tuple[str, ...]


DEFECTS = [
    Defect(
        "La limite max_steps n'est pas lue",
        "src/kaldera/runner.py",
        "    if state.step_count >= limit:\n",
        "    if state.step_count >= HARD_CAP:\n",
        ("test_step_guard_stops_at_limit",),
    ),
    Defect(
        "La condition de fin est décalée d'un cran (>)",
        "src/kaldera/orchestrator.py",
        "if state.step_index >= len(state.required_steps):",
        "if state.step_index > len(state.required_steps):",
        ("test_route_returns_end_once_all_steps_done", "test_scenario_completes_within_budget"),
    ),
    Defect(
        "Le chef passe lui-même le statut à done",
        "src/kaldera/runner.py",
        '    if decision == END:\n        if state.status != "done":',
        '    if decision == END:\n        state.status = "done"\n'
        '        if state.status != "done":',
        ("test_missing_closure_is_detected",),
    ),
    Defect(
        "La table confie REVIEW au writer",
        "src/kaldera/orchestrator.py",
        "STEP_TO_ARTIFACT: dict[Step, str] = {step: a.produces for a in AGENTS for step in a.handles}\n",
        "STEP_TO_ARTIFACT: dict[Step, str] = {step: a.produces for a in AGENTS for step in a.handles}\n"
        'STEP_TO_AGENT[Step.REVIEW] = "writer"\n',
        (
            "test_review_is_routed_to_reviewer",
            "test_routing_table_matches_owners",
            "test_each_step_is_done_by_its_owner",
        ),
    ),
    Defect(
        "Le writer déclare aussi REVIEW",
        "src/kaldera/agents/writer.py",
        "handles = frozenset({Step.DRAFT})",
        "handles = frozenset({Step.DRAFT, Step.REVIEW})",
        ("test_each_step_handled_by_exactly_one_agent",),
    ),
    Defect(
        "Le writer accepte toutes les étapes",
        "src/kaldera/agents/writer.py",
        '    produces = "draft"\n',
        '    produces = "draft"\n\n    def accepts(self, step):\n        return True\n',
        ("test_every_agent_refuses_every_foreign_step", "test_writer_refuses_foreign_step"),
    ),
    Defect(
        "Writer et researcher ont la même description",
        "src/kaldera/agents/writer.py",
        'description = "Rédige un premier jet à partir de la recherche, sans le relire."',
        'description = "Collecte et synthétise les informations nécessaires au sujet traité."',
        ("test_agent_descriptions_are_distinct",),
    ),
    Defect(
        "Le finalizer est absent de l'équipe",
        "src/kaldera/orchestrator.py",
        "AGENTS = [Researcher(), Writer(), Reviewer(), Finalizer()]",
        "AGENTS = [Researcher(), Writer(), Reviewer()]",
        ("test_finalizer_is_registered", "test_scenario_completes_within_budget"),
    ),
    Defect(
        "Le journal n'enregistre pas l'agent",
        "src/kaldera/logging_utils.py",
        '        "agent_id": agent_id,\n',
        "",
        ("test_log_entry_carries_agent_id",),
    ),
    Defect(
        "Le budget de tokens n'est jamais comparé",
        "src/kaldera/agents/base.py",
        "        if used > self.token_budget:",
        "        if False:",
        ("test_per_agent_token_budget_is_enforced", "test_budget_exceeded_stops_flow"),
    ),
    Defect(
        "La demande n'est pas lue",
        "src/kaldera/runner.py",
        '    context = scenario.get("initial_context", {})\n',
        '    return\n    context = scenario.get("initial_context", {})\n',
        ("test_load_context_populates_state", "test_scenario_completes_within_budget"),
    ),
    Defect(
        "PROOFREAD au lieu de REVIEW",
        "src/kaldera/steps.py",
        "STEP_BY_NAME: dict[str, Step] = {step.value: step for step in Step}",
        "STEP_BY_NAME: dict[str, Step] = {\n"
        '    ("PROOFREAD" if step is Step.REVIEW else step.value): step for step in Step\n}',
        ("test_review_label_resolves_to_review_step", "test_all_business_labels_resolve"),
    ),
    Defect(
        "Un agent bloqué est relancé sans fin",
        "src/kaldera/runner.py",
        "    if state.retry_used:\n",
        "    if False:\n",
        ("test_stuck_agent_is_stopped_after_one_retry",),
    ),
    # Défauts propres à l'orchestration cible : chaque renfort doit lui aussi être prouvé.
    Defect(
        "Le chef ne contrôle pas la progression faite par l'agent",
        "src/kaldera/runner.py",
        "        and progression_ok\n",
        "",
        ("test_agent_cannot_drive_progression",),
    ),
    Defect(
        "Les écritures d'un passage refusé ne sont pas annulées",
        "src/kaldera/runner.py",
        "    store.restore(snapshot)\n",
        "",
        ("test_refused_writes_are_rolled_back",),
    ),
    Defect(
        "Un agent autre que le finalizer peut passer à done",
        "src/kaldera/runner.py",
        "        and (state.status == status or step is Step.FINALIZE)\n",
        "",
        ("test_only_finalizer_can_close",),
    ),
    Defect(
        "Les écritures hors registre ne sont pas vues",
        "src/kaldera/runner.py",
        "written | changed == {expected}",
        "written == {expected}",
        ("test_writes_outside_the_role_are_detected",),
    ),
    Defect(
        "La relance n'est pas remise à zéro d'une étape à l'autre",
        "src/kaldera/runner.py",
        "        state.retry_used = False\n        return\n",
        "        return\n",
        ("test_retry_is_granted_once_per_step",),
    ),
    Defect(
        "FINALIZE accepté ailleurs qu'en dernière position",
        "src/kaldera/orchestrator.py",
        '        return "finalize_not_last"\n',
        "        pass\n",
        ("test_invalid_demands_are_refused",),
    ),
    Defect(
        "Un état déjà entamé est accepté au départ",
        "src/kaldera/orchestrator.py",
        '        return "state_not_fresh"\n',
        "        pass\n",
        ("test_state_already_started_is_refused",),
    ),
    Defect(
        "Un agent qui plante arrête le flux sans code",
        "src/kaldera/runner.py",
        "    except Exception:\n        failure = error_code\n",
        "",
        ("test_unexpected_agent_error_is_stopped",),
    ),
    Defect(
        "Le chemin live contourne le chef",
        "src/kaldera/graph.py",
        '            chef_turn(state, agent, name, llm=llm, error_code="llm_error")\n',
        "            agent.run(state, llm=llm)\n            state.step_count += 1\n"
        "            state.advance()\n",
        (
            "test_live_journal_matches_the_deterministic_chief",
            "test_live_path_retries_once_then_stops",
        ),
    ),
]

FAILED = re.compile(r"^(?:FAILED|ERROR) tests/\S+?::(\w+)(?:\[[^\]]*\])?(?: - (\S+?):)?", re.M)


def run_tests(root: Path) -> tuple[int, dict[str, str]]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-rf",
            "tests",
            "--deselect",
            "tests/test_graph.py::test_run_live_completes_with_a_real_llm",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    failed = {m.group(1): (m.group(2) or "échec") for m in FAILED.finditer(proc.stdout)}
    return proc.returncode, failed


def main() -> int:
    rows, ok = [], True
    with tempfile.TemporaryDirectory(prefix="kaldera_grille_") as tmp:
        base = Path(tmp) / "ref"
        for name in COPIED:
            src = REPO / name
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, base / name)
        code, failed = run_tests(base)
        if code != 0:
            print(f"Référence en échec, grille impossible : {sorted(failed)}")
            return 1
        for index, defect in enumerate(DEFECTS, 1):
            work = Path(tmp) / f"d{index}"
            shutil.copytree(base, work)
            target = work / defect.path
            text = target.read_text(encoding="utf-8")
            if text.count(defect.old) != 1:
                rows.append((index, defect.label, "injection impossible", "non disponible", "NON"))
                ok = False
                continue
            target.write_text(text.replace(defect.old, defect.new), encoding="utf-8")
            _, failed = run_tests(work)
            caught = [t for t in defect.expected if t in failed]
            verdict = "OUI" if caught else "NON"
            ok &= bool(caught)
            detail = ", ".join(f"{t} ({failed[t]})" for t in caught) or "aucun test désigné"
            rows.append((index, defect.label, detail, str(len(failed)), verdict))
    width = max(len(r[1]) for r in rows)
    print("Référence : tous les tests passent sans défaut.\n")
    for index, label, detail, count, verdict in rows:
        print(f"{index:>2} | {label:<{width}} | attrapé : {verdict} | {count} test(s) en échec")
        print(f"   |   {detail}")
    print(
        f"\nRésultat : {'chaque défaut est attrapé' if ok else 'au moins un défaut échappe aux tests'}."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
