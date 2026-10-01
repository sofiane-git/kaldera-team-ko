"""Fiches lisibles des artefacts produits par l'équipe, à la place d'un bloc JSON.

Une fiche par artefact, dans l'ordre où le flux les construit : son nom en clair, l'agent qui
l'a écrit, l'étape, son état (vide, en écriture, accepté) et son contenu en texte. Une flèche
entre deux fiches dit de quel artefact le suivant est construit. Aucun import de `gradio`.
"""

from __future__ import annotations

import html
from collections.abc import Mapping

from ..orchestrator import STEP_TO_AGENT, STEP_TO_ARTIFACT

ORDER = ("research", "draft", "review", "final")
LABELS = {
    "research": ("Recherche", "Les informations collectées sur le sujet."),
    "draft": ("Premier jet", "Le texte rédigé à partir de la recherche."),
    "review": ("Relecture", "La version corrigée du premier jet."),
    "final": ("Résultat final", "Ce que l'équipe livre."),
}
BUILT_FROM = {"draft": "research", "review": "draft"}
_OWNER = {artifact: STEP_TO_AGENT[step] for step, artifact in STEP_TO_ARTIFACT.items()}
_STEP = {artifact: step.value for step, artifact in STEP_TO_ARTIFACT.items()}
_FINAL_SOURCES = ("review", "draft", "research")


def _final_source(artifacts: Mapping[str, str]) -> str | None:
    return next((key for key in _FINAL_SOURCES if key in artifacts), None)


def _card(key: str, value: str | None, author: str | None, state: str) -> str:
    title, hint = LABELS.get(key, (key, "Artefact hors fiches de poste."))
    step = _STEP.get(key, "")
    styles = {
        "accepted": ("#15803D", "#F0FDF4", "accepté"),
        "writing": ("#B45309", "#FFFBEB", "en écriture…"),
        "empty": ("#94A3B8", "#F8FAFC", "vide"),
    }
    border, background, state_label = styles[state]
    if value:
        body = (
            f'<div class="ka-text">{html.escape(value)}</div>'
            f'<div class="ka-meta">{len(value)} caractères</div>'
        )
    else:
        body = '<div class="ka-empty">pas encore produit</div>'
    who = (
        f"écrit par <b>{html.escape(author)}</b>"
        if author
        else f"attendu de <b>{_OWNER.get(key, '?')}</b>"
    )
    return (
        f'<div class="ka-card" style="border-color:{border};background:{background}">'
        f'<div class="ka-head"><span class="ka-title">{html.escape(title)}</span>'
        f'<span class="ka-badge" style="background:{border}">{state_label}</span></div>'
        f'<div class="ka-sub">{html.escape(hint)}</div>'
        f'<div class="ka-sub">{who}{f" · étape {step}" if step else ""} · clé <code>{html.escape(key)}</code></div>'
        f"{body}</div>"
    )


def _arrow(text: str) -> str:
    return f'<div class="ka-arrow">↓ {html.escape(text)}</div>'


def render_artifacts_html(
    artifacts: Mapping[str, str] | None,
    authors: Mapping[str, str] | None = None,
    writing: str | None = None,
    expected: list[str] | None = None,
) -> str:
    """Fiches des artefacts. `authors` donne l'agent de chaque artefact accepté (par défaut, son
    propriétaire) ; `writing` désigne l'artefact en cours d'écriture, encore non accepté ;
    `expected` limite les fiches aux artefacts que la demande produira."""
    artifacts = dict(artifacts or {})
    authors = dict(authors or {})
    wanted = set(expected) if expected is not None else set(ORDER)
    keys = [k for k in ORDER if k in wanted or k in artifacts or k == writing]
    keys += [k for k in artifacts if k not in ORDER]
    parts = []
    for index, key in enumerate(keys):
        value = artifacts.get(key)
        state = "accepted" if value is not None else ("writing" if key == writing else "empty")
        author = authors.get(key) or (_OWNER.get(key) if value is not None else None)
        if index:
            previous = keys[index - 1]
            if key == "final":
                source = _final_source(artifacts) if "final" in artifacts else None
                text = (
                    f"construit sur {LABELS[source][0].lower()}"
                    if source
                    else "sera construit sur l'artefact le plus abouti"
                )
                parts.append(_arrow(text))
            elif BUILT_FROM.get(key) == previous:
                parts.append(_arrow(f"construit à partir de : {LABELS[previous][0].lower()}"))
            else:
                parts.append('<div class="ka-gap"></div>')
        parts.append(_card(key, value, author, state))
    produced = sum(1 for k in keys if k in artifacts)
    return (
        '<div class="kart" style="background:#FFFFFF;color:#1F2330;border:1px solid #E2E8F0;'
        'border-radius:12px;padding:12px;font-family:Arial,sans-serif">'
        "<style>.kart .ka-card{border:2px solid;border-radius:10px;padding:10px 12px}"
        ".kart .ka-head{display:flex;justify-content:space-between;align-items:center;gap:8px}"
        ".kart .ka-title{font-weight:700;font-size:15px}"
        ".kart .ka-badge{color:#fff;font-size:12px;border-radius:999px;padding:2px 10px}"
        ".kart .ka-sub{color:#475569;font-size:12px;margin-top:3px}"
        ".kart code{background:#EEF2F7;border-radius:4px;padding:0 4px}"
        ".kart .ka-text{margin-top:8px;white-space:pre-wrap;word-break:break-word;font-size:14px;"
        "line-height:1.45;max-height:220px;overflow:auto;background:#fff;border:1px solid #E2E8F0;"
        "border-radius:6px;padding:8px}"
        ".kart .ka-meta{color:#94A3B8;font-size:11px;margin-top:4px;text-align:right}"
        ".kart .ka-empty{margin-top:8px;color:#94A3B8;font-style:italic;font-size:13px}"
        ".kart .ka-arrow{color:#64748B;font-size:12px;text-align:center;margin:6px 0}"
        ".kart .ka-gap{height:10px}</style>"
        f'<div style="font-size:13px;color:#475569;margin-bottom:8px">Artefacts produits : '
        f"<b>{produced} sur {len(keys)}</b></div>"
        f"{''.join(parts)}</div>"
    )
