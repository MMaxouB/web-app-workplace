from pathlib import Path

from core.obsidian.models import Collaborator, Project, Task


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
