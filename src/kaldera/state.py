"""État partagé d'une exécution de l'équipe."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .steps import Step


@dataclass
class Write:
    """Une écriture d'artefact : qui, à quelle étape, quelle clé (suppression comprise)."""

    agent: str | None
    step: Step | None
    key: str
    deleted: bool = False
    refused: bool = False


class ArtifactStore(dict[str, str]):
    """Artefacts partagés, avec le registre de chaque écriture et de chaque suppression.

    Le registre note toute écriture, même quand la valeur ne change pas : c'est ce qui permet
    au chef de voir un agent réécrire à l'identique l'artefact d'un autre. Une écriture qui
    contournerait le registre (appel direct à `dict`) reste visible pour le chef, qui compare
    aussi le contenu avant et après chaque agent.
    """

    def __init__(self, *args: object, **kwargs: str) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.writes: list[Write] = []
        self.writer: tuple[str, Step] | None = None

    def _note(self, key: str, deleted: bool = False) -> None:
        agent, step = self.writer if self.writer is not None else (None, None)
        self.writes.append(Write(agent, step, key, deleted))

    def __setitem__(self, key: str, value: str) -> None:
        self._note(key)
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self._note(key, deleted=True)
        super().__delitem__(key)

    def __ior__(self, other: object) -> ArtifactStore:  # type: ignore[override,misc]
        self.update(other)
        return self

    def update(self, *args: object, **kwargs: str) -> None:  # type: ignore[override]
        for key, value in dict(*args, **kwargs).items():  # type: ignore[arg-type]
            self[key] = value

    def setdefault(self, key: str, default: str = "") -> str:  # type: ignore[override]
        if key not in self:
            self[key] = default
        return self[key]

    def pop(self, key: str, *default: str) -> str:  # type: ignore[override]
        if key in self:
            self._note(key, deleted=True)
        return super().pop(key, *default)

    def popitem(self) -> tuple[str, str]:
        key, value = super().popitem()
        self._note(key, deleted=True)
        return key, value

    def clear(self) -> None:
        for key in list(self):
            self._note(key, deleted=True)
        super().clear()

    def restore(self, snapshot: Mapping[str, str]) -> None:
        """Remet le contenu d'avant un passage refusé, sans l'inscrire au registre."""
        dict.clear(self)
        dict.update(self, snapshot)


@dataclass
class TeamState:
    topic: str | None = None
    required_steps: list[Step] = field(default_factory=list)
    step_index: int = 0
    artifacts: ArtifactStore = field(default_factory=ArtifactStore)
    status: str = "pending"
    step_count: int = 0
    agent_tokens: dict[str, int] = field(default_factory=dict)
    log: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    step_limit: int | None = None
    # Relance déjà accordée pour l'étape courante (une seule par étape, décision D3).
    retry_used: bool = False
    # Agent choisi par le chef pour le prochain tour (chemin live : le routage LangGraph le lit).
    next_agent: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, ArtifactStore):
            self.artifacts = ArtifactStore(self.artifacts)

    def current_step(self) -> Step | None:
        if self.step_index >= len(self.required_steps):
            return None
        return self.required_steps[self.step_index]

    def advance(self) -> None:
        self.step_index += 1

    @property
    def incomplete(self) -> set[str]:
        """Artefacts écrits pendant un passage refusé (annulé), jamais acceptés depuis."""
        refused = {w.key for w in self.artifacts.writes if w.refused}
        accepted = {w.key for w in self.artifacts.writes if not w.refused}
        return refused - accepted
