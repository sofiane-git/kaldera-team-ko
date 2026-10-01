"""Point d'entrée : rejoue les scénarios fournis, ou lance un flux live (--live)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run_scenario

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios" / "scenarios_test.json"


def _print_state(label: str, state) -> None:
    print(
        f"[{label}] status={state.status} "
        f"steps={state.step_count} artifacts={sorted(state.artifacts)}"
        + (f" stop_reason={state.stop_reason}" if state.stop_reason else "")
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kaldera — rejoue les scénarios fournis, ou lance un flux live (vrai LLM)."
    )
    parser.add_argument(
        "--live", metavar="SUJET", help="lance un flux réel (vrai LLM) sur ce sujet"
    )
    parser.add_argument(
        "--steps",
        default="RESEARCH,DRAFT,REVIEW,FINALIZE",
        help="étapes du flux --live, séparées par des virgules (défaut : %(default)s)",
    )
    args = parser.parse_args()

    if args.live is not None:
        from .graph import run_live

        state = run_live(args.live, args.steps.split(","))
        _print_state("live", state)
        for key in sorted(state.artifacts):
            print(f"\n--- {key} ---\n{state.artifacts[key]}")
        return

    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    for scenario in data["scenarios"]:
        _print_state(scenario["id"], run_scenario(scenario))


if __name__ == "__main__":
    main()
