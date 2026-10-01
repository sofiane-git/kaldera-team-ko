# Développement · ce qui a été fait, et pourquoi

Brief Kaldera « L'équipe d'agents qui se marche dessus » · Phase DÉVELOPPEMENT · mis à jour le 01/10/2026

- **Point de départ** : commit `37c2cb3`, où les 14 tests fournis échouaient tous.
- **Référence de conception** : `doc/livrable_conception/note_diagnostic_et_schema_cible.md`, avec
  les décisions D1 à D9 validées le 30/09/2026.

---

## En bref : les 5 points du brief sont traités

| Point du brief                                                      | Réponse                                                                                                                                | Preuve                                                                                  |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| 1 · Clarifier les rôles et frontières des sub-agents                | une étape et un artefact par agent, déclarés une seule fois ; table du chef déduite ; refus effectif hors du rôle                      | tests du dessin de l'équipe ; grille, défauts 4 à 7                                     |
| 2 · Corriger l'orchestration (fin de boucle, arbitrage, délégation) | le chef confie, réceptionne, relance une fois ou arrête ; il tient le compte des étapes ; les deux chemins d'exécution passent par lui | tests boucles, arrêts et conflits ; parité des chemins ; grille, défauts 1 à 3, 13 à 22 |
| 3 · Réaligner le flux sur la spécification métier                   | demande lue et vérifiée avant tout travail ; ordre exact ; seul le finalizer clôt ; codes d'arrêt                                      | scénarios fournis en `done` ; tests des demandes invalides ; grille, défauts 8 à 12     |
| 4 · Vérifier la non-régression sur les scénarios fournis            | les 14 tests et les 2 scénarios fournis passent, sans avoir été modifiés                                                               | `git diff 37c2cb3` sur les tests et scénarios fournis : un seul commentaire ajouté      |
| 5 · Documenter les choix                                            | ce document, les notes de conception mises à jour, le README, les journaux                                                             | section « Où trouver quoi », en fin de document                                         |

**En chiffres** :
- 131 tests passent, dont les 14 fournis ;
- 22 défauts réintroduits un à un, tous attrapés par au moins un test ;
- `ruff` et `mypy` ne signalent rien ;
- le chemin live a été vérifié avec le vrai LLM Azure.

---

## 1. Clarifier les rôles et frontières des sub-agents

**Le problème de départ.** Le rôle d'un agent était écrit à trois endroits qui se contredisaient :
la table du chef, la liste `handles` et la méthode `accepts`. Résultat : le writer revendiquait
`REVIEW`, l'acceptait toujours, et y réécrivait son brouillon. Le reviewer n'était jamais appelé.

**Ce qui a été fait.**

| Agent      | Étape (la seule) | Lit                                       | Écrit (seul propriétaire)   | Fichier                |
| ---------- | ---------------- | ----------------------------------------- | --------------------------- | ---------------------- |
| researcher | `RESEARCH`       | le sujet                                  | `research`                  | `agents/researcher.py` |
| writer     | `DRAFT`          | `research`                                | `draft`                     | `agents/writer.py`     |
| reviewer   | `REVIEW`         | `draft`                                   | `review` (version corrigée) | `agents/reviewer.py`   |
| finalizer  | `FINALIZE`       | `review`, sinon `draft`, sinon `research` | `final` et statut `done`    | `agents/finalizer.py`  |

- **Un rôle, une seule déclaration.** Chaque agent déclare `handles` et `produces`. La table du chef
  (`STEP_TO_AGENT`), la liste des artefacts attendus, le refus hors du rôle et le prompt système
  s'en déduisent (`orchestrator.py`, `agents/base.py`). Une contradiction devient impossible par
  construction.
- **Le refus hors du rôle est effectif.** Plus aucun agent ne contourne `accepts`. Une étape étrangère
  lève `RoleViolation`, et le chef arrête le flux en `role_violation`.
- **Les descriptions sont distinctes.** Le writer avait la description du researcher.
- **L'équipe est vérifiée avant le départ.** Chaque étape doit avoir exactement un propriétaire, et
  chaque agent doit porter le nom de sa place dans l'équipe (motif `team_incomplete`).

**Pourquoi ainsi.** La conception (point 2) a montré que le conflit sur `REVIEW` venait de trois
déclarations divergentes. Les rassembler en une seule supprime la cause, au lieu de seulement
corriger le symptôme.

---

## 2. Corriger l'orchestration : fin de boucle, arbitrage, délégation

**Le problème de départ.** Le chef déléguait sans réceptionner. Un agent bloqué était rappelé 50 fois,
parce que la limite `max_steps` n'était jamais lue. Après la dernière étape, le chef plantait. Et
c'est l'agent lui-même qui faisait avancer le flux.

**Ce qui a été fait.** Le chef se trouve dans `runner.py`, sous forme de trois fonctions :

1. `prepare` note la limite d'étapes, puis vérifie la demande et l'équipe ;
2. `chef_decide` décide de la suite : l'agent suivant, la fin (`done` seulement si le finalizer a
   clos, sinon `missing_closure`), ou l'arrêt sur la limite (`step_limit_reached`) ;
3. `chef_turn` fait une délégation complète.

`chef_turn` se déroule ainsi :
- **délégation** : il confie l'étape au seul propriétaire, et le journalise ;
- **réception** : seul l'artefact attendu doit être écrit, et rien d'autre ne doit avoir changé
  dans l'état (la demande, l'étape courante, le compte des étapes, le statut) ;
- **arbitrage**, selon les issues suivantes :

| Issue                                        | Ce que fait le chef                                                                                         |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| conforme                                     | il accepte et avance d'une étape ; c'est lui, et non l'agent, qui avance                                    |
| non conforme, première fois                  | il annule le passage et accorde **une seule relance** (D3), journalisée                                     |
| non conforme une seconde fois                | il annule le passage et arrête en `reception_refused`                                                       |
| hors rôle, budget dépassé, erreur de l'agent | il annule le passage et arrête aussitôt (`role_violation`, `budget_exceeded`, `agent_error` ou `llm_error`) |

**Pourquoi la boucle se termine toujours.** Le chef tient lui-même le compte des étapes confiées, et
le rétablit après chaque agent. Chaque tour confie une étape ou termine, et le compte est comparé à
la limite avant chaque délégation. Un agent ne peut donc ni sauter une étape, ni rallonger la
boucle.

**Un passage refusé est annulé.** L'état revient à ce qu'il était avant l'agent, et les écritures
annulées restent visibles au registre, marquées comme refusées. Le registre d'écriture
(`state.py`, `ArtifactStore`) note chaque écriture et chaque suppression, même à valeur identique.
Le chef compare aussi le contenu des artefacts avant et après chaque agent, ce qui voit une écriture
qui contournerait le registre.

**Un seul chef pour les deux chemins.** Le chemin déterministe enchaîne `chef_decide` et `chef_turn`.
Le chemin « live » (`graph.py`, LangGraph + vrai LLM) les appelle dans ses nœuds : le superviseur
décide, le nœud de chaque agent fait son tour. La réception, la relance unique, l'annulation et le
journal du chef sont donc identiques. Un test vérifie que les deux chemins produisent le même journal
du chef (`tests/test_graph_chef_partage.py`). Le vrai LLM est appelé via `langchain-openai`, sur
l'endpoint Azure AI compatible OpenAI (`llm.py`).

**Pourquoi ainsi.** La conception (point 1) a montré que la boucle naissait d'un chef qui délègue sans
réceptionner. Réunir délégation et réception au même endroit, avec un compte que seul le chef tient,
supprime le chemin de la boucle. Une revue de code indépendante a ensuite fait ajouter l'annulation
des passages refusés et le contrôle de la progression. Sans eux, un agent pouvait encore piloter le
flux ou contaminer la suite.

---

## 3. Réaligner le flux sur la spécification métier

| Exigence de `specs/flow_spec.md`                   | Ce qui l'applique                                                                  |
| -------------------------------------------------- | ---------------------------------------------------------------------------------- |
| étapes dans l'ordre fourni par la demande (l. 3-4) | `load_context` lit la demande ; le chef suit l'ordre exact, sans sauter ni ajouter |
| les quatre étapes métier (l. 8-13)                 | `REVIEW` reconnu : la table des libellés se déduit de l'énumération (`steps.py`)   |
| un seul agent par étape (l. 26-27)                 | point 1 de ce document                                                             |
| refus hors du périmètre (l. 22)                    | `RoleViolation` effectif                                                           |
| jamais plus de `max_steps` (l. 29)                 | limite lue et appliquée avant chaque délégation                                    |
| budget de tokens par agent (l. 33-34)              | consommation comparée au budget ; `BudgetExceeded`                                 |
| journal avec l'identifiant de l'agent (l. 35-36)   | chaque entrée porte l'agent, l'étape et l'action, y compris pour le chef           |
| le finalizer assemble `final` et clôt (l. 20)      | finalizer dans l'équipe ; seul à passer à `done`                                   |
| fin explicite `END` (l. 28)                        | condition de fin corrigée (`>=`) ; sans clôture, `missing_closure`                 |

**La demande est vérifiée avant tout travail** (D4). Une demande invalide ne démarre pas, et s'arrête
en `invalid_demand` avec un motif :

| Motif               | Cas refusé                                                  |
| ------------------- | ----------------------------------------------------------- |
| `empty`             | sujet vide (y compris des espaces seuls) ou aucune étape    |
| `unknown_label`     | libellé qui n'est pas une étape de la spécification         |
| `state_not_fresh`   | état déjà entamé (statut, étape courante ou artefacts)      |
| `duplicate_step`    | étape demandée deux fois                                    |
| `finalize_not_last` | `FINALIZE` demandé ailleurs qu'en dernier                   |
| `missing_input`     | étape sans son entrée (par exemple `DRAFT` sans `RESEARCH`) |
| `too_many_steps`    | plus d'étapes que la limite                                 |
| `team_incomplete`   | étape sans propriétaire unique, ou agent mal nommé          |
| `invalid_limit`     | limite qui n'est pas un entier positif ou nul               |

**Lecture de `max_steps`.** La spécification place cette limite dans la demande. Elle est donc lue
d'abord dans `initial_context`, puis dans `expected` (là où les scénarios fournis la placent), puis
fixée à 50 par défaut. Les scénarios fournis ne sont pas modifiés. Cette lecture, ajoutée par le
binôme, fait évoluer D6, qui lisait seulement `expected`.

**`FINALIZE` n'est pas exigé** (D5). S'il est demandé, il doit être en dernier. Une demande sans
`FINALIZE` va jusqu'au bout, puis s'arrête en `missing_closure`, puisque personne ne peut clore.

---

## 4. Vérifier la non-régression sur les scénarios de test fournis

| Contrôle                                                     | Résultat                                                                       |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| 14 tests fournis                                             | 14 passent (0 au départ)                                                       |
| Tests et scénarios fournis inchangés                         | depuis `37c2cb3`, seul un commentaire a été ajouté dans `tests/test_runner.py` |
| Scénario `happy_path`                                        | `done`, 4 étapes : researcher, writer, reviewer, finalizer                     |
| Scénario `research_only`                                     | `done`, 2 étapes : researcher, finalizer                                       |
| Suite complète                                               | 131 tests passent                                                              |
| Test du vrai LLM (`test_run_live_completes_with_a_real_llm`) | passe avec les identifiants Azure ; il est sauté sans eux                      |
| Grille de preuve (`scripts/grille_de_preuve.py`)             | 22 défauts réintroduits un à un, 22 attrapés ; la référence passe              |
| `ruff check`, `mypy src`                                     | aucun défaut                                                                   |

**Pourquoi une grille de preuve.** Un test qui n'a jamais échoué ne prouve rien. La grille copie le
dépôt dans un dossier temporaire et y réintroduit chaque défaut, un à la fois. Il y en a deux sortes :
- les 13 défauts du diagnostic ;
- 9 défauts propres à la cible, par exemple « le chemin live contourne le chef ».

Pour chaque défaut, au moins un test désigné doit échouer. Le dépôt lui-même n'est jamais modifié.
La grille exclut le test du vrai LLM, qui dépend du réseau et non du code.

**Les tests ajoutés**, par fichier :

| Fichier                             | Cas | Ce qu'il vérifie                                                                      |
| ----------------------------------- | --- | ------------------------------------------------------------------------------------- |
| `test_orchestration_cible.py`       | 37  | dessin de l'équipe, boucles, arrêts, conflits, demandes invalides, invariants I1 à I7 |
| `test_graph_chef_partage.py`        | 7   | le chemin live suit le même chef : journal identique, relance, annulation, limite     |
| `test_graph.py` (binôme)            | 4   | câblage du graphe, limite, refus de rôle, vrai LLM                                    |
| `test_max_steps_source.py` (binôme) | 2   | `max_steps` lu dans la demande, puis dans `expected`                                  |
| `test_cli.py` (binôme)              | 2   | CLI : rejeu des scénarios et option `--live`                                          |
| `test_webapp_*.py`                  | 65  | GUI : exécution, garde-fous, coût, vue animée, fiches d'artefacts, adresse d'écoute   |

---

## 5. Documenter les choix

### Décisions validées, et comment elles ont évolué

| Décision | Contenu                                                           | Évolution pendant le Développement                                       |
| -------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------ |
| D1       | le reviewer produit la version corrigée, sans renvoyer au writer  | aucune                                                                   |
| D2       | le chef fait avancer l'étape, après réception                     | étendue au chemin live                                                   |
| D3       | une relance unique, seulement après une réception refusée         | étendue au chemin live                                                   |
| D4       | demande et équipe vérifiées avant tout travail                    | motifs ajoutés : `state_not_fresh`, `finalize_not_last`, `invalid_limit` |
| D5       | `FINALIZE` non exigé au départ                                    | précisée : s'il est demandé, il doit être en dernier                     |
| D6       | `max_steps` lu dans `expected`, `max_iterations` prime            | lu d'abord dans la demande, comme le veut la spécification               |
| D7       | `final` construit sur l'artefact le plus abouti                   | aucune                                                                   |
| D8       | codes d'arrêt stables, journal du chef                            | codes ajoutés : `agent_error`, `llm_error`                               |
| D9       | tests et scénarios fournis intacts, tests nouveaux à côté, grille | grille étendue de 13 à 22 défauts                                        |

### Écarts avec la conception initiale, et pourquoi

- **Un passage refusé est annulé, et non conservé.** La revue de code a montré qu'un artefact
  conservé contaminait la suite du flux.
- **Le chef a été factorisé** en `prepare`, `chef_decide` et `chef_turn`, pour que le chemin live le
  réutilise au lieu d'en être une copie divergente. C'était l'exigence de la conception (point 3,
  section 6) que le premier câblage du graphe ne respectait pas.

### Ce qui n'est pas couvert

- **Le budget de tokens repose sur un coût fixe par étape** (`step_cost`), pas sur les tokens
  réellement consommés par le LLM.
- **Un agent qui écrirait dans l'état en contournant toutes les interfaces** n'est pas bloqué au
  moment où il écrit. Mais le chef voit l'écart à la réception, et il annule le passage.
- **Un artefact vide renvoyé par le LLM est accepté.** La réception vérifie que l'artefact est
  présent, pas la qualité de son contenu.

### Où trouver quoi

| Besoin                                  | Emplacement                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------------ |
| Diagnostic et schéma cible              | `doc/livrable_conception/note_diagnostic_et_schema_cible.md`                         |
| Raisonnement point par point            | `doc/conception_point_1_…` à `doc/conception_point_4_…`                              |
| Le chef                                 | `src/kaldera/runner.py` (`prepare`, `chef_decide`, `chef_turn`)                      |
| Les rôles                               | `src/kaldera/agents/`, `src/kaldera/orchestrator.py`                                 |
| Le chemin live                          | `src/kaldera/graph.py`, `src/kaldera/llm.py`                                         |
| La GUI (architecture animée, artefacts) | `src/kaldera/webapp/`, lancée par `make webapp`, puis ouvrir `http://localhost:7860` |
| La grille de preuve                     | `scripts/grille_de_preuve.py`                                                        |
| Les journaux de session                 | `doc/journal/`                                                                       |

---

## Rejouer

Depuis la racine du dépôt :

```bash
uv sync --extra webapp
uv run python -m pytest -p no:cacheprovider -q
uv run python scripts/grille_de_preuve.py
uv run python -m kaldera.cli
make webapp        # puis ouvrir http://localhost:7860
```

Sur ce poste, `pytest.exe` est bloqué par la stratégie de contrôle d'application : il faut passer
par `python -m pytest`. Sous PowerShell, définir `$env:PYTHONIOENCODING = 'utf-8'` avant la grille.
