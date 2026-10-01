"""Le chef : il confie, réceptionne, avance ou arrête.

Un seul chef sert les deux chemins d'exécution :
- le chemin déterministe (`run_scenario`) enchaîne `chef_decide` et `chef_turn` dans une boucle ;
- le chemin « live » (`graph.py`, LangGraph + vrai LLM) appelle `chef_decide` dans le nœud
  superviseur et `chef_turn` dans le nœud de chaque agent.
Les règles (réception, relance unique, annulation d'un passage refusé, journal du chef) sont donc
les mêmes partout.
"""

from __future__ import annotations

from .agents.base import BudgetExceeded, RoleViolation
from .logging_utils import record
from .orchestrator import AGENTS_BY_NAME, END, STEP_TO_ARTIFACT, SUPERVISOR, check_demand, route
from .state import ArtifactStore, TeamState
from .steps import Step, step_from_name

# Limite par défaut quand ni l'appelant ni le scénario n'en fixent une.
HARD_CAP = 50
_ABSENT = object()


def load_context(state: TeamState, scenario: dict) -> None:
    """Lit le sujet et les étapes de la demande ; un libellé inconnu lève `KeyError`."""
    context = scenario.get("initial_context", {})
    state.topic = context.get("topic")
    state.required_steps = [step_from_name(name) for name in context.get("required_steps", [])]


def _stop(state: TeamState, code: str, step: Step | None = None) -> TeamState:
    state.status = "aborted"
    state.stop_reason = code
    record(state, SUPERVISOR, f"arrêt : {code}", step)
    return state


def _artifacts_ok(
    store: ArtifactStore, snapshot: dict[str, str], first_write: int, step: Step
) -> bool:
    """Seul l'artefact attendu a été écrit, et il est présent.

    Le registre voit les réécritures à l'identique ; la comparaison avec l'instantané voit
    les écritures qui contourneraient le registre.
    """
    expected = STEP_TO_ARTIFACT[step]
    written = {w.key for w in store.writes[first_write:]}
    changed = {
        key
        for key in set(snapshot) | set(store)
        if snapshot.get(key, _ABSENT) != store.get(key, _ABSENT)
    }
    return expected in written and expected in store and written | changed == {expected}


def prepare(state: TeamState, registry: dict, limit: int) -> bool:
    """Note la limite et vérifie la demande avant tout travail ; `False` si le flux s'arrête."""
    state.step_limit = limit
    record(state, SUPERVISOR, f"limite d'étapes : {limit}")
    motif = check_demand(state, registry, limit)
    if motif is not None:
        _stop(state, f"invalid_demand:{motif}")
        return False
    return True


def chef_decide(state: TeamState, limit: int) -> str | None:
    """Décide de la suite : renvoie l'agent à qui confier l'étape, ou `None` si le flux finit.

    La fin n'est `done` que si le finalizer a clos ; sinon `missing_closure`. Le compte des
    étapes confiées appartient au chef (`chef_turn` le rétablit après chaque agent).
    """
    if state.status == "aborted":
        return None
    decision = route(state)
    if decision == END:
        if state.status != "done":
            _stop(state, "missing_closure")
            return None
        record(state, SUPERVISOR, "fin : flux clos par le finalizer")
        return None
    step = state.current_step()
    assert step is not None
    if state.step_count >= limit:
        _stop(state, "step_limit_reached", step)
        return None
    return decision


def chef_turn(
    state: TeamState,
    agent: object,
    decision: str,
    llm: object | None = None,
    error_code: str = "agent_error",
) -> None:
    """Une délégation complète : confier, faire travailler l'agent, réceptionner.

    Le passage est accepté (l'étape avance), refusé une fois (relance unique, `retry_used`), ou
    arrêté avec un code. Un passage refusé est annulé. `error_code` nomme l'arrêt quand l'agent
    lève une erreur imprévue (`llm_error` sur le chemin live).
    """
    step = state.current_step()
    assert step is not None
    record(state, SUPERVISOR, f"confie {step.value} à {decision}", step)
    store = state.artifacts
    snapshot, first_write = dict(store), len(store.writes)
    index, steps, status = state.step_index, list(state.required_steps), state.status
    delegations = state.step_count + 1
    state.step_count = delegations
    store.writer = (decision, step)
    failure: str | None = None
    try:
        if llm is None:
            agent.run(state)  # type: ignore[attr-defined]
        else:
            agent.run(state, llm=llm)  # type: ignore[attr-defined]
    except RoleViolation:
        failure = "role_violation"
    except BudgetExceeded:
        failure = "budget_exceeded"
    except Exception:
        failure = error_code
    finally:
        store.writer = None

    progression_ok = (
        state.artifacts is store
        and state.step_index == index
        and state.step_count == delegations
        and state.required_steps == steps
    )
    # Le chef reprend la main sur l'état, quoi qu'ait fait l'agent.
    state.artifacts, state.step_index, state.required_steps = store, index, steps
    state.step_count = delegations
    accepted = (
        failure is None
        and progression_ok
        and _artifacts_ok(store, snapshot, first_write, step)
        and (state.status == status or step is Step.FINALIZE)
    )
    if accepted:
        record(state, SUPERVISOR, f"réception acceptée : {step.value}", step)
        state.advance()
        state.retry_used = False
        return

    # Passage refusé : ses écritures sont annulées et restent tracées comme refusées.
    for write in store.writes[first_write:]:
        write.refused = True
    store.restore(snapshot)
    state.status = status
    if failure is not None:
        _stop(state, failure, step)
        return
    if state.retry_used:
        _stop(state, "reception_refused", step)
        return
    record(state, SUPERVISOR, f"réception refusée : {step.value}, relance unique", step)
    state.retry_used = True


def run_scenario(
    scenario: dict,
    max_iterations: int | None = None,
    agents_by_name: dict | None = None,
    initial_state: TeamState | None = None,
) -> TeamState:
    state = initial_state if initial_state is not None else TeamState()
    registry = agents_by_name if agents_by_name is not None else AGENTS_BY_NAME
    # La spécification place `max_steps` dans la demande (`initial_context`) ; les scénarios
    # fournis le placent dans `expected`. On lit la demande en priorité, sans modifier les
    # scénarios fournis (D9), et `expected` reste le repli pour ceux-ci.
    limit = (
        max_iterations
        if max_iterations is not None
        else scenario.get("initial_context", {}).get("max_steps")
    )
    if limit is None:
        limit = scenario.get("expected", {}).get("max_steps")
    if limit is None:
        limit = HARD_CAP
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        state.step_limit = 0
        record(state, SUPERVISOR, f"limite d'étapes : {limit}")
        return _stop(state, "invalid_demand:invalid_limit")
    if initial_state is None:
        try:
            load_context(state, scenario)
        except KeyError:
            state.step_limit = limit
            record(state, SUPERVISOR, f"limite d'étapes : {limit}")
            return _stop(state, "invalid_demand:unknown_label")
    if not prepare(state, registry, limit):
        return state

    # Chaque tour confie une étape (le chef compte) ou termine : la limite borne la boucle.
    while (decision := chef_decide(state, limit)) is not None:
        chef_turn(state, registry[decision], decision)
    return state
