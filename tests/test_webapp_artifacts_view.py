"""Fiches d'artefacts : lisibles par un humain, dans l'ordre du flux, sûres face au texte saisi."""

from kaldera.webapp import runners
from kaldera.webapp.artifacts_view import render_artifacts_html

ALL_STEPS = ["RESEARCH", "DRAFT", "REVIEW", "FINALIZE"]


def test_cards_follow_the_flow_with_human_labels_and_authors():
    result = runners.run_deterministic("lancement produit", ALL_STEPS)
    page = render_artifacts_html(result["artifacts"])
    titles = ["Recherche", "Premier jet", "Relecture", "Résultat final"]
    positions = [page.index(t) for t in titles]
    assert positions == sorted(positions)
    for agent in ("researcher", "writer", "reviewer", "finalizer"):
        assert f"écrit par <b>{agent}</b>" in page
    assert "4 sur 4" in page and page.count("accepté") == 4
    assert "construit à partir de : recherche" in page and "construit sur relecture" in page
    assert "lancement produit" in page  # le contenu est montré en texte, pas en JSON
    assert '{"' not in page


def test_only_expected_artifacts_get_a_card():
    result = runners.run_deterministic("note", ["RESEARCH", "FINALIZE"])
    page = render_artifacts_html(result["artifacts"], expected=["research", "final"])
    assert "Premier jet" not in page and "Relecture" not in page
    assert "2 sur 2" in page and "construit sur recherche" in page


def test_empty_and_writing_states_are_visible():
    page = render_artifacts_html({}, writing="research", expected=["research", "final"])
    assert "en écriture…" in page and "pas encore produit" in page and "0 sur 2" in page
    assert "attendu de <b>researcher</b>" in page


def test_given_author_wins_over_the_default_owner():
    page = render_artifacts_html({"research": "r"}, {"research": "intrus"}, expected=["research"])
    assert "écrit par <b>intrus</b>" in page


def test_unknown_artifact_is_still_shown():
    page = render_artifacts_html({"research": "r", "notes": "n"}, expected=["research"])
    assert "Artefact hors fiches de poste." in page and "notes" in page


def test_artifact_text_is_escaped():
    page = render_artifacts_html(
        {"research": '<img src=x onerror="alert(1)">'}, expected=["research"]
    )
    assert "<img" not in page and "&lt;img" in page


def test_empty_view_without_any_run():
    page = render_artifacts_html(None)
    assert "0 sur 4" in page and page.count("pas encore produit") == 4


def test_final_source_is_not_announced_before_the_final_exists():
    page = render_artifacts_html(
        {"research": "r", "draft": "d"}, expected=["research", "draft", "final"]
    )
    assert "sera construit sur l&#x27;artefact le plus abouti" in page  # apostrophe échappée
    assert "construit sur premier jet" not in page
