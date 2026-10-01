"""Construction et exécution du chemin « live » (LangGraph + vrai LLM).

Le graphe ne réimplémente pas le chef : il réutilise celui de `runner.py`.
- Le nœud superviseur appelle `chef_decide` : fin, arrêt sur la limite, ou agent suivant.
- Le nœud de chaque agent appelle `chef_turn` : délégation, réception, relance unique,
  annulation d'un passage refusé, journal du chef.
Les règles sont donc identiques au chemin déterministe. Seule différence : l'agent répond par un
vrai appel LLM, et une erreur imprévue de l'agent (réseau, LLM) s'arrête en `llm_error`.

Les décisions du chef sont prises dans un nœud, jamais dans la fonction de routage : LangGraph
ne conserve pas les changements d'état faits pendant le routage.
"""

from __future__ import annotations

from .llm import build_llm
from .orchestrator import AGENTS_BY_NAME, END, SUPERVISOR, route
from .runner import HARD_CAP, chef_decide, chef_turn, prepare
from .state import TeamState
from .steps import step_from_name


def build_graph(llm: object, limit: int = HARD_CAP):
    from langgraph.graph import END as LG_END
    from langgraph.graph import StateGraph

    registry = AGENTS_BY_NAME

    def supervisor(state: TeamState) -> TeamState:
        state.next_agent = chef_decide(state, limit)
        return state

    def make_node(name: str, agent: object):
        def node(state: TeamState) -> TeamState:
            chef_turn(state, agent, name, llm=llm, error_code="llm_error")
            return state

        return node

    def route_from_state(state: TeamState) -> str:
        return state.next_agent or "__end__"

    graph = StateGraph(TeamState)
    graph.add_node(SUPERVISOR, supervisor)
    for name, agent in registry.items():
        graph.add_node(name, make_node(name, agent))
        graph.add_edge(name, SUPERVISOR)

    graph.add_conditional_edges(
        SUPERVISOR,
        route_from_state,
        {**{name: name for name in registry}, "__end__": LG_END},
    )
    graph.set_entry_point(SUPERVISOR)
    return graph.compile()


def run_live(topic: str, required_steps: list[str], max_steps: int | None = None) -> TeamState:
    """Exécute un flux réel : vrai LLM, même chef que le chemin déterministe."""
    state = TeamState(topic=topic, required_steps=[step_from_name(s) for s in required_steps])
    limit = max_steps if max_steps is not None else HARD_CAP
    if not prepare(state, AGENTS_BY_NAME, limit):
        return state

    llm = build_llm()
    graph = build_graph(llm, limit)
    result = graph.invoke(state, {"recursion_limit": 4 * limit + 10})
    return TeamState(**result) if isinstance(result, dict) else result


__all__ = ["build_graph", "run_live", "route", "END", "TeamState"]
