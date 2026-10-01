"""Vue animée de l'architecture agentique : par où passe la donnée, étape par étape.

Le journal d'une exécution est découpé en « images » (`Frame`), et chaque image est dessinée en
SVG : la demande, le chef, les quatre sub-agents, l'état partagé et ses artefacts, la fin et
l'arrêt. La flèche active s'allume, un point animé la parcourt dans le sens de la donnée, et une
étiquette dit ce qui est transporté. Aucun import de `gradio` : module testable seul.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from ..orchestrator import STEP_TO_AGENT, STEP_TO_ARTIFACT, SUPERVISOR
from ..steps import Step

AGENT_ORDER = ("researcher", "writer", "reviewer", "finalizer")
ARTIFACT_ORDER = ("research", "draft", "review", "final")
READS = {
    "researcher": "le sujet",
    "writer": "research",
    "reviewer": "draft",
    "finalizer": "review › draft › research",
}
_STEP_OF_AGENT = {agent: step.value for step, agent in STEP_TO_AGENT.items()}
_ARTIFACT_OF_STEP = {step.value: artifact for step, artifact in STEP_TO_ARTIFACT.items()}


@dataclass
class Frame:
    """Une image de l'animation : ce qui se passe, et l'état visible à ce moment."""

    kind: str  # check | delegate | work | accept | refuse | stop | end
    text: str
    agent: str | None = None
    step: str | None = None
    artifact: str | None = None
    payload: str = ""
    store: dict[str, tuple[str, str]] = field(default_factory=dict)  # clé -> (auteur, valeur)
    done_agents: tuple[str, ...] = ()
    step_count: int = 0
    status: str = "pending"
    stop_reason: str | None = None


# --------------------------------------------------------------------- construction des images


def _preview(value: str, limit: int = 70) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


class _Builder:
    def __init__(self, artifacts: dict[str, str]) -> None:
        self.final_values = dict(artifacts)
        self.frames: list[Frame] = []
        self.store: dict[str, tuple[str, str]] = {}
        self.done: list[str] = []
        self.count = 0

    def add(self, kind: str, text: str, **kw: object) -> None:
        status = str(kw.pop("status", "pending"))
        self.frames.append(
            Frame(
                kind,
                text,
                store=dict(self.store),
                done_agents=tuple(self.done),
                step_count=self.count,
                status=status,
                **kw,  # type: ignore[arg-type]
            )
        )

    def mark_last_work_rejected(self) -> None:
        """Un travail suivi d'un refus n'a rien laissé d'utilisable : l'image le dit."""
        last = self.frames[-1] if self.frames else None
        if last is not None and last.kind == "work":
            last.kind = "reject_work"
            last.text = f"{last.agent} rend la main sans {last.artifact} conforme"
            last.payload = f"∅ {last.artifact} absent ou non conforme"

    def accept(self, agent: str, step: str, value: str | None = None) -> None:
        artifact = _ARTIFACT_OF_STEP.get(step)
        if artifact is not None:
            shown = value if value is not None else self.final_values.get(artifact, "")
            self.store[artifact] = (agent, shown)
        if agent not in self.done:
            self.done.append(agent)
        self.add(
            "accept",
            f"Le chef réceptionne {step} : conforme, il avance",
            agent=agent,
            step=step,
            artifact=artifact,
            payload=f"✓ {artifact} accepté",
        )


def frames_from_log(
    log: list[dict],
    artifacts: dict[str, str],
    topic: str = "",
    status: str = "",
    stop: str | None = None,
) -> list[Frame]:
    """Images d'une exécution du chef déterministe (`runner.run_scenario`), à partir de son journal."""
    b = _Builder(artifacts)
    current: tuple[str, str] | None = None
    for entry in log:
        who, message, step = entry.get("agent_id"), entry.get("message", ""), entry.get("step")
        if who == SUPERVISOR and message.startswith("limite d'étapes"):
            b.add(
                "check",
                f"Le chef reçoit la demande et la vérifie ({message})",
                payload=f"sujet : {_preview(topic, 40)}" if topic else "demande",
            )
        elif who == SUPERVISOR and message.startswith("confie"):
            agent = message.rsplit(" ", 1)[-1]
            current = (agent, step or "")
            b.count += 1
            b.add(
                "delegate",
                f"Le chef confie {step} à {agent}",
                agent=agent,
                step=step,
                payload=f"{step} · lit {READS.get(agent, '?')}",
            )
        elif who != SUPERVISOR and message.startswith("a traité"):
            artifact = _ARTIFACT_OF_STEP.get(step or "")
            value = artifacts.get(artifact or "", "")
            b.add(
                "work",
                f"{who} écrit {artifact} dans l'état partagé",
                agent=who,
                step=step,
                artifact=artifact,
                payload=f"{artifact} = {_preview(value) or '…'}",
            )
        elif who == SUPERVISOR and message.startswith("réception acceptée"):
            agent = current[0] if current else STEP_TO_AGENT[Step(step)]
            b.accept(agent, step or "")
        elif who == SUPERVISOR and message.startswith("réception refusée"):
            agent = current[0] if current else ""
            b.mark_last_work_rejected()
            b.add(
                "refuse",
                f"Le chef refuse le travail de {agent} sur {step} : relance unique",
                agent=agent,
                step=step,
                payload="✗ non conforme · relance",
            )
        elif who == SUPERVISOR and message.startswith("arrêt"):
            code = message.split(":", 1)[-1].strip()
            if code == "reception_refused":
                b.mark_last_work_rejected()
            agent = current[0] if current else None
            b.add(
                "stop",
                f"Arrêt du flux : {code}",
                agent=agent,
                step=step,
                payload=code,
                status="aborted",
                stop_reason=code,
            )
        elif who == SUPERVISOR and message.startswith("fin"):
            b.add("end", "Le finalizer a clos le flux : END", payload="final livré", status="done")
    if not b.frames or b.frames[-1].kind not in ("stop", "end"):
        if status == "aborted":
            b.add(
                "stop",
                f"Arrêt du flux : {stop}",
                payload=str(stop),
                status="aborted",
                stop_reason=stop,
            )
        elif status == "done":
            b.add("end", "Le flux est clos : END", payload="final livré", status="done")
    return b.frames


def frames_from_live(chunks: list[dict], topic: str = "") -> list[Frame]:
    """Images du chemin « vrai LLM » (`runners.stream_live`), qui journalise les seuls agents."""
    if not chunks:
        return []
    b = _Builder(chunks[-1].get("artifacts", {}))
    b.add(
        "check",
        "Le chef reçoit la demande et la vérifie",
        payload=f"sujet : {_preview(topic, 40)}" if topic else "demande",
    )
    seen = 0
    for chunk in chunks:
        log = chunk.get("log", [])
        for entry in log[seen:]:
            agent, step = (
                entry.get("agent_id"),
                entry.get("step") or _STEP_OF_AGENT.get(entry.get("agent_id", ""), ""),
            )
            if agent == SUPERVISOR:
                continue
            artifact = _ARTIFACT_OF_STEP.get(step)
            value = chunk.get("artifacts", {}).get(artifact or "", "")
            b.count += 1
            b.add(
                "delegate",
                f"Le chef confie {step} à {agent}",
                agent=agent,
                step=step,
                payload=f"{step} · lit {READS.get(agent, '?')}",
            )
            b.add(
                "work",
                f"{agent} écrit {artifact} (réponse du LLM)",
                agent=agent,
                step=step,
                artifact=artifact,
                payload=f"{artifact} = {_preview(value) or '…'}",
            )
            b.accept(agent, step, value)
        seen = len(log)
    last = chunks[-1]
    if last.get("status") == "aborted":
        b.add(
            "stop",
            f"Arrêt du flux : {last.get('stop_reason')}",
            payload=str(last.get("stop_reason")),
            status="aborted",
            stop_reason=last.get("stop_reason"),
        )
    elif last.get("status") == "done":
        b.add("end", "Le finalizer a clos le flux : END", payload="final livré", status="done")
    return b.frames


# --------------------------------------------------------------------------------- rendu SVG

_W, _H = 1000, 620
_CHEF = (400, 40, 200, 76)
_DEMANDE = (30, 48, 170, 60)
_END = (820, 30, 150, 44)
_ABORT = (820, 92, 150, 44)
_AGENT_Y, _AGENT_W, _AGENT_H = 250, 190, 92
_AGENT_X = {name: 20 + i * 245 for i, name in enumerate(AGENT_ORDER)}
_STORE = (230, 452, 540, 140)
_CHIP_X = {name: 248 + i * 130 for i, name in enumerate(ARTIFACT_ORDER)}

_COLORS = {
    "check": "#6366F1",
    "delegate": "#7C3AED",
    "work": "#0F766E",
    "reject_work": "#B45309",
    "accept": "#15803D",
    "refuse": "#B91C1C",
    "stop": "#B91C1C",
    "end": "#15803D",
}


def _agent_center(name: str) -> tuple[float, float]:
    return _AGENT_X[name] + _AGENT_W / 2, _AGENT_Y + _AGENT_H / 2


def _path(kind: str, agent: str | None, artifact: str | None) -> str | None:
    """Tracé de la flèche active, orienté dans le sens où circule la donnée."""
    cx = _agent_center(agent)[0] if agent in _AGENT_X else None
    if kind == "check":
        return f"M{_DEMANDE[0] + _DEMANDE[2]},78 L{_CHEF[0]},78"
    if kind == "delegate" and cx is not None:
        return f"M{_CHEF[0] + 100},{_CHEF[1] + _CHEF[3]} C{_CHEF[0] + 100},180 {cx},170 {cx},{_AGENT_Y}"
    if kind in ("accept", "refuse") and cx is not None:
        return f"M{cx},{_AGENT_Y} C{cx},170 {_CHEF[0] + 100},180 {_CHEF[0] + 100},{_CHEF[1] + _CHEF[3]}"
    if kind in ("work", "reject_work") and cx is not None and artifact in _CHIP_X:
        tx = _CHIP_X[artifact] + 57
        return f"M{cx},{_AGENT_Y + _AGENT_H} C{cx},420 {tx},400 {tx},{_STORE[1] + 46}"
    if kind == "end":
        return f"M{_CHEF[0] + _CHEF[2]},62 L{_END[0]},52"
    if kind == "stop":
        return f"M{_CHEF[0] + _CHEF[2]},92 L{_ABORT[0]},114"
    return None


def _static_edges() -> str:
    parts = [f'<path d="M{_DEMANDE[0] + _DEMANDE[2]},78 L{_CHEF[0]},78" class="edge"/>']
    for name in AGENT_ORDER:
        cx = _agent_center(name)[0]
        parts.append(
            f'<path d="M{_CHEF[0] + 100},{_CHEF[1] + _CHEF[3]} C{_CHEF[0] + 100},180 {cx},170 {cx},{_AGENT_Y}" class="edge"/>'
        )
        parts.append(
            f'<path d="M{cx},{_AGENT_Y + _AGENT_H} L{cx},{_STORE[1]}" class="edge faint"/>'
        )
    parts.append(f'<path d="M{_CHEF[0] + _CHEF[2]},62 L{_END[0]},52" class="edge"/>')
    parts.append(f'<path d="M{_CHEF[0] + _CHEF[2]},92 L{_ABORT[0]},114" class="edge"/>')
    return "".join(parts)


def _box(
    x: float, y: float, w: float, h: float, cls: str, title: str, lines: list[str], rx: int = 10
) -> str:
    out = [f'<g class="{cls}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>']
    out.append(f'<text x="{x + w / 2}" y="{y + 24}" class="t-title">{html.escape(title)}</text>')
    for i, line in enumerate(lines):
        out.append(
            f'<text x="{x + w / 2}" y="{y + 44 + i * 17}" class="t-line">{html.escape(line)}</text>'
        )
    out.append("</g>")
    return "".join(out)


def render_flow_svg(frame: Frame | None, topic: str = "") -> str:
    kind = frame.kind if frame else ""
    active_agent = frame.agent if frame else None
    color = _COLORS.get(kind, "#6366F1")
    parts = [
        f'<svg viewBox="0 0 {_W} {_H}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Architecture agentique : {html.escape(frame.text) if frame else "en attente"}">',
        "<style>"
        ".edge{fill:none;stroke:#CBD5E1;stroke-width:2}.faint{stroke-dasharray:4 4}"
        ".t-title{font:700 15px Arial;text-anchor:middle}.t-line{font:12px Arial;text-anchor:middle}"
        ".chef rect{fill:#34307A}.chef text{fill:#fff}"
        ".agent rect{fill:#E6F4F2;stroke:#0F766E;stroke-width:1.5}.agent text{fill:#0F3F3A}"
        ".agent.done rect{fill:#DCFCE7;stroke:#15803D}"
        ".agent.active rect{stroke:#F59E0B;stroke-width:4}"
        ".agent.bad rect{fill:#FDECEC;stroke:#B91C1C;stroke-width:3}"
        ".io rect{fill:#E9ECF2;stroke:#6B7280}.io text{fill:#1F2330}"
        ".end rect{fill:#F0FDF4;stroke:#86EFAC}.end text{fill:#14532D}"
        ".end.on rect{fill:#22C55E;stroke:#15803D}.end.on text{fill:#fff}"
        ".abort rect{fill:#FEF2F2;stroke:#FECACA}.abort text{fill:#7F1D1D}"
        ".abort.on rect{fill:#DC2626;stroke:#991B1B}.abort.on text{fill:#fff}"
        ".store>rect{fill:#F8FAFC;stroke:#64748B;stroke-width:1.5}"
        ".chip rect{fill:#fff;stroke:#CBD5E1;stroke-dasharray:4 3}.chip text{fill:#94A3B8}"
        ".chip.full rect{fill:#ECFDF5;stroke:#15803D;stroke-dasharray:none}.chip.full text{fill:#14532D}"
        ".chip.hot rect{stroke:#F59E0B;stroke-width:3;stroke-dasharray:none}"
        ".pkt rect{fill:#fff;stroke-width:2}.pkt text{font:600 12px Arial;text-anchor:middle}"
        "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}.blink{animation:pulse 1s infinite}"
        "</style>",
        _static_edges(),
    ]
    # Nœuds
    parts.append(_box(*_DEMANDE, "io", "Demande", [_preview(topic, 22) or "sujet + étapes"]))
    parts.append(_box(*_CHEF, "chef", "Chef · superviseur", ["confie · réceptionne · arrête"]))
    parts.append(_box(*_END, "end on" if kind == "end" else "end", "END · done", [], rx=22))
    parts.append(_box(*_ABORT, "abort on" if kind == "stop" else "abort", "aborted", [], rx=22))
    if frame and kind == "stop" and frame.stop_reason:
        parts.append(
            f'<text x="{_ABORT[0] + _ABORT[2] / 2}" y="{_ABORT[1] + _ABORT[3] + 18}" '
            f'class="t-title" fill="#B91C1C">{html.escape(_preview(frame.stop_reason, 26))}</text>'
        )
    for name in AGENT_ORDER:
        cls = "agent"
        if frame and name in frame.done_agents:
            cls += " done"
        if name == active_agent and kind in ("refuse", "stop"):
            cls += " bad"
        elif name == active_agent:
            cls += " active"
        step = _STEP_OF_AGENT.get(name, "")
        produces = _ARTIFACT_OF_STEP.get(step, "")
        badge = " ✓" if frame and name in frame.done_agents else ""
        parts.append(
            _box(
                _AGENT_X[name],
                _AGENT_Y,
                _AGENT_W,
                _AGENT_H,
                cls,
                f"{name}{badge}",
                [step, f"lit : {READS[name]}", f"écrit : {produces}"],
            )
        )
    # État partagé et artefacts
    sx, sy, sw, sh = _STORE
    parts.append(
        f'<g class="store"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="14"/>'
        f'<text x="{sx + sw / 2}" y="{sy + 24}" class="t-title" fill="#334155">État partagé · registre d\'écriture</text></g>'
    )
    for name in ARTIFACT_ORDER:
        x = _CHIP_X[name]
        entry = frame.store.get(name) if frame else None
        cls = "chip full" if entry else "chip"
        writing = bool(
            frame and frame.artifact == name and kind in ("work", "reject_work", "accept")
        )
        if writing:
            cls += " hot"
        author = f"par {entry[0]}" if entry else ("en écriture…" if writing else "vide")
        value = _preview(entry[1], 16) if entry else ""
        parts.append(
            f'<g class="{cls}"><rect x="{x}" y="{sy + 40}" width="114" height="84" rx="8"/>'
            f'<text x="{x + 57}" y="{sy + 62}" class="t-title">{name}</text>'
            f'<text x="{x + 57}" y="{sy + 82}" class="t-line">{html.escape(author)}</text>'
            f'<text x="{x + 57}" y="{sy + 100}" class="t-line">{html.escape(value)}</text></g>'
        )
    # Flèche active, point animé et paquet de données
    d = _path(kind, active_agent, frame.artifact if frame else None)
    if frame and d:
        parts.append(
            f'<path id="active" d="{d}" fill="none" stroke="{color}" stroke-width="5" '
            f'stroke-linecap="round" class="blink"/>'
        )
        parts.append(
            f'<circle r="9" fill="{color}" stroke="#fff" stroke-width="2">'
            f'<animateMotion dur="1.1s" repeatCount="indefinite" path="{d}"/></circle>'
        )
        label = _preview(frame.payload, 46)
        lx, ly = _label_anchor(kind, active_agent, frame.artifact)
        width = max(110, 7.2 * len(label) + 24)
        parts.append(
            f'<g class="pkt"><rect x="{lx - width / 2}" y="{ly - 15}" width="{width}" height="26" '
            f'rx="13" stroke="{color}"/><text x="{lx}" y="{ly + 3}" fill="{color}">{html.escape(label)}</text></g>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _label_anchor(kind: str, agent: str | None, artifact: str | None) -> tuple[float, float]:
    if kind == "check":
        return (_DEMANDE[0] + _DEMANDE[2] + _CHEF[0]) / 2, 136
    if kind in ("end", "stop"):
        return 700, 176
    cx = _agent_center(agent)[0] if agent in _AGENT_X else 500
    if kind in ("work", "reject_work"):
        tx = _CHIP_X.get(artifact or "", 450) + 57
        return min(max((cx + tx) / 2, 130), 870), 412
    return min(max((cx + 500) / 2, 130), 870), 196


def render_flow_html(
    frame: Frame | None, history: list[Frame] | None = None, topic: str = ""
) -> str:
    """Bloc HTML complet : le schéma animé, la légende et le fil des événements."""
    history = history or []
    status = frame.status if frame else "en attente"
    counter = f"étapes confiées : {frame.step_count}" if frame else ""
    now = html.escape(frame.text) if frame else "Lance une exécution pour voir la donnée circuler."
    rows = []
    for i, f in enumerate(history[-12:], start=max(1, len(history) - 11)):
        dot = _COLORS.get(f.kind, "#6366F1")
        rows.append(f'<li><span style="background:{dot}"></span>{i}. {html.escape(f.text)}</li>')
    legend = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{t}</span>'
        for t, c in (
            ("vérifie", _COLORS["check"]),
            ("confie", _COLORS["delegate"]),
            ("écrit", _COLORS["work"]),
            ("non conforme", _COLORS["reject_work"]),
            ("accepte", _COLORS["accept"]),
            ("refuse / arrête", _COLORS["refuse"]),
        )
    )
    return (
        '<div class="kflow" style="background:#FFFFFF;color:#1F2330;border:1px solid #E2E8F0;'
        'border-radius:12px;padding:12px;font-family:Arial,sans-serif">'
        "<style>.kflow .now{font-weight:700;font-size:15px;margin:4px 0 8px}"
        ".kflow .meta{color:#475569;font-size:13px}.kflow ol{list-style:none;padding:0;margin:8px 0 0;"
        "font-size:13px;max-height:220px;overflow:auto}.kflow li{margin:2px 0}"
        ".kflow li span{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}"
        ".kflow .lg{margin-right:12px;font-size:12px;color:#475569}.kflow .lg i{display:inline-block;"
        "width:18px;height:4px;border-radius:2px;margin-right:4px;vertical-align:middle}</style>"
        f'<div class="meta">statut : <b>{html.escape(status)}</b> · {counter}</div>'
        f'<div class="now">▶ {now}</div>'
        f"{render_flow_svg(frame, topic)}"
        f'<div style="margin-top:6px">{legend}</div>'
        f"<ol>{''.join(rows)}</ol></div>"
    )
