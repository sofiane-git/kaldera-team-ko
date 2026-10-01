# Kaldera Team KO

Orchestrateur d'une équipe d'agents LLM (`researcher`, `writer`, `reviewer`,
`finalizer`) coordonnés par un superviseur, pour traiter une demande métier
étape par étape jusqu'à un résultat final.

## Features

- Superviseur qui confie chaque étape à l'agent responsable via une table de routage.
- Sous-agents spécialisés, chacun avec un périmètre de rôle explicite.
- Exécution déterministe et rejouable à partir de scénarios JSON.
- Garde-fous d'exécution : budget d'étapes, budget de tokens par agent, journalisation traçable.
- Chemin d'exécution « live » branché sur Azure AI (Kimi-K2.6) via LangChain + LangGraph.

## Stack

- Python 3.11 (uv)
- LangChain / langchain-core 0.3.x
- langchain-openai 0.3.x (appel réel, endpoint Azure AI compatible OpenAI)
- langchain-azure-ai 0.1.x (déclaré, non utilisé : cible l'API azure-ai-inference,
  incompatible avec l'endpoint `/openai/v1` fourni)
- LangGraph 0.2.x
- pytest 8.x

## Setup

```bash
make install              # uv sync — installe les dépendances
cp .env.example .env      # puis renseigner les clés Azure AI
make up                   # docker compose up -d (conteneur d'exécution)
make test                 # lance la suite de tests
```

Sans Docker, `make install` puis `make test` suffisent : le cœur de
l'orchestration tourne sans dépendance réseau.

## Layout

- `src/kaldera/` — superviseur, sous-agents, état partagé, garde-fous d'exécution
- `src/kaldera/agents/` — `researcher`, `writer`, `reviewer`, `finalizer`
- `src/kaldera/graph.py`, `src/kaldera/llm.py` — chemin d'exécution branché sur le LLM
- `specs/flow_spec.md` — spécification du flux métier attendu
- `scenarios/scenarios_test.json` — scénarios d'exécution rejouables
- `tests/` — tests unitaires et d'intégration
- `docker-compose.yml`, `Dockerfile` — service d'exécution conteneurisé

## Useful commands

```bash
make fmt        # ruff format + autofix
make lint       # ruff check
make typecheck  # mypy
make down       # stoppe le service docker
```

## Known issues

Les trois limites connues de la PR précédente sont résolues :

- Le chemin « live » (`graph.py`, LangGraph) câble un flux réel : mêmes garde-fous que le
  runner déterministe (rôle, budget, limite d'étapes, clôture par le finalizer), un vrai appel
  LLM par étape. Voir `run_live()` et `tests/test_graph.py`.
- Un vrai LLM est testé (`tests/test_graph.py::test_run_live_completes_with_a_real_llm`,
  se saute si `AZURE_AI_ENDPOINT`/`AZURE_AI_API_KEY`/`AZURE_AI_MODEL` sont absents).
- `max_steps` est lu dans la demande (`initial_context`) en priorité, conformément à
  `specs/flow_spec.md`, avec repli sur `expected` puis sur une limite par défaut — sans modifier
  les scénarios fournis.

Reste ouvert : le budget de tokens reste un coût fixe par étape (`step_cost`), pas un compte
réel des tokens consommés par le LLM.

Les boucles, le conflit sur `REVIEW` et les garde-fous ont été corrigés : voir
`doc/developpement/choix_de_developpement.md`. Pour prouver que chaque défaut corrigé serait
détecté s'il revenait : `uv run python scripts/grille_de_preuve.py`.

## GUI de démo

Une GUI Gradio pédagogique (déterministe / vrai LLM / casser un garde-fou / comparer les deux)
tourne en local et sur Azure Container Apps.

**En local :**

```bash
make webapp
# ou, sans passer par le Makefile :
uv sync --extra webapp
uv run python -m kaldera.webapp.app
```

Ouvre `http://localhost:7860` (et non `http://0.0.0.0:7860`, que le navigateur refuse). Si le
port est déjà pris, une instance tourne déjà : utilise-la, ou arrête-la (Ctrl+C) avant de relancer.

**Architecture en direct.** En tête des onglets « Exécuter » et « Casser un garde-fou », un schéma
animé montre l'équipe (demande, chef, quatre sub-agents, état partagé, fin ou arrêt) et, étape par
étape, **par où passe la donnée** : la flèche active s'allume, un point la parcourt dans le sens
de la donnée, une étiquette dit ce qui est transporté, et l'état partagé se remplit à chaque
réception acceptée. Le curseur règle la vitesse (secondes par étape). Code : `src/kaldera/webapp/flow_view.py`.

**En production :** `<URL Azure Container Apps — à renseigner après le premier déploiement, voir
doc/guides/deploiement_azure_portail.md>`. Démarrage à froid possible (scale-to-zero) : ouvrir
l'URL une minute avant une démo.

**Déployer/relire l'infrastructure :**
- `doc/guides/deploiement_azure_portail.md` — créer les ressources Azure (portail, pas à pas).
- `doc/guides/github_actions_azure_oidc_portail.md` — connecter la CI à Azure sans secret
  longue durée.
- `.github/workflows/ci-cd.yml` — tests sur chaque PR, build + déploiement automatique sur `main`.

## License

Usage interne — tous droits réservés.
