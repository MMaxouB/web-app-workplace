from pathlib import Path

from core.obsidian.models import (
    Collaborator,
    Knowledge,
    Note,
    Project,
    Task,
)


def test_project_model():
    project = Project(
        path=Path("project.md"),
        type="project",
        status="active",
        name="AI Video Editor",
        category="software",
        priority="high",
        created="2026-08-01",
        deadline="X",
        repository="https://example.com",
    )

    assert project.name == "AI Video Editor"
    assert project.status == "active"
    assert project.priority == "high"


def test_collaborator_model():
    collaborator = Collaborator(
        path=Path("kyel.md"),
        type="collaborator",
        status="active",
        name="Kyel",
        role=None,
        company=None,
        discord="kyel0820",
        email=None,
        github=None,
        website=None,
        timezone="US ?",
        joined="2026-08-13",
    )

    assert collaborator.name == "Kyel"
    assert collaborator.discord == "kyel0820"


def build_task(**overrides) -> Task:
    fields = {
        "path": Path("task.md"),
        "name": "task",
        "type": "task",
        "status": "active",
        "priority": "medium",
        "platform": "Discord",
        "project": "Refonte espace de travail",
        "collaborator": "Moi",
        "created": "2026-08-13T23:04:57+02:00",
        "deadline": "14j",
        "due": "2026-08-27T23:04:57+02:00",
        "completed": None,
    }

    fields.update(overrides)

    return Task(**fields)


def test_task_model():
    task = build_task()

    assert task.status == "active"
    assert task.priority == "medium"
    assert task.platform == "Discord"


def test_filename_differs_from_name():
    project = Project(
        path=Path("02-Projects/AI-Powered Video Editor.md"),
        type="project",
        status="active",
        name="AI Video Editor",
        category="software",
        priority="high",
        created=None,
        deadline=None,
        repository=None,
    )

    assert project.name == "AI Video Editor"
    assert project.filename == "AI-Powered Video Editor"


def test_task_is_open():
    assert build_task(status="active").is_open
    assert build_task(status="waiting").is_open
    assert not build_task(status="completed").is_open
    assert not build_task(status="archived").is_open


def build_knowledge(**overrides) -> Knowledge:
    fields = {
        "path": Path("06-Connaissances/Cybersecurity/Web/XSS stockee.md"),
        "type": "knowledge",
        "name": "XSS stockee",
        "categorie": "technique",
        "domaine": "Cybersecurity",
        "sujet": "Web",
        "maturite": "stable",
        "tags": ("xss", "dom"),
        "source": "https://example.invalid/xss",
        "created": "2026-08-18",
        "mis_a_jour": "2026-08-18",
    }

    fields.update(overrides)

    return Knowledge(**fields)


def test_knowledge_model():
    note = build_knowledge()

    assert note.categorie == "technique"
    assert note.maturite == "stable"
    assert note.tags == ("xss", "dom")


def test_le_nom_d_une_connaissance_est_son_fichier():
    """La convention interdit un champ `name:` : le titre est le nom."""
    note = build_knowledge()

    assert note.name == note.filename == "XSS stockee"


def build_note(**overrides) -> Note:
    fields = {
        "path": Path("07-Notes/Points Alpha.md"),
        "type": "note",
        "name": "Points Alpha",
        "project": "Projet Alpha",
        "sujet": "points a verifier",
        "created": "2026-08-18",
        "mis_a_jour": "2026-08-18",
    }

    fields.update(overrides)

    return Note(**fields)


def test_note_model():
    note = build_note()

    assert note.project == "Projet Alpha"
    assert note.filename == "Points Alpha"


def test_une_note_n_a_ni_statut_ni_priorite():
    """La convention est explicite : aucune criticité sur une note."""
    champs = {champ.name for champ in Note.__dataclass_fields__.values()}

    assert not champs & {"status", "priority", "due", "deadline"}


def test_note_is_archived_depend_du_dossier():
    assert build_note(
        path=Path("07-Notes/Archives/Ancienne.md")
    ).is_archived

    assert not build_note(path=Path("07-Notes/Vivante.md")).is_archived
