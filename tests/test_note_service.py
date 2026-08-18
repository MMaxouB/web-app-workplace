"""Ajout de notes libres, sur Vault temporaire."""

import datetime

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import VaultWriter
from core.services.collaborators import CollaboratorService
from core.services.notes import (
    NoteError,
    NoteService,
    format_note,
    resolve_kind,
    split_target_and_text,
)
from core.services.projects import ProjectService
from core.services.tasks import TaskService


@pytest.fixture
def service(
    temp_vault: ObsidianVault,
    temp_repository: ObsidianRepository,
) -> NoteService:
    writer = VaultWriter(temp_vault)

    return NoteService(
        temp_repository,
        writer,
        TaskService(temp_repository, writer),
        ProjectService(temp_repository, writer),
        CollaboratorService(temp_repository, writer),
    )


MOMENT = datetime.datetime(2026, 8, 14, 20, 30)


# =====================================================
# Analyse des arguments
# =====================================================


def test_resolve_kind():
    assert resolve_kind("projet") == "project"
    assert resolve_kind("Tâche") == "task"
    assert resolve_kind("collaborateur") == "collaborator"
    assert resolve_kind("n_importe_quoi") is None


def test_split_avec_egal():
    nom, texte = split_target_and_text(
        '"AI Video Editor" = le compositeur fonctionne'
    )

    assert nom == "AI Video Editor"
    assert texte == "le compositeur fonctionne"


def test_split_avec_guillemets_seuls():
    nom, texte = split_target_and_text(
        '"AI Video Editor" le compositeur fonctionne'
    )

    assert nom == "AI Video Editor"
    assert texte == "le compositeur fonctionne"


def test_split_sans_repere_echoue():
    """Sans guillemets ni « = », on ne devine pas où couper."""
    assert split_target_and_text("AI Video Editor du texte") == (
        "",
        "",
    )
    assert split_target_and_text("") == ("", "")


def test_format_note():
    resultat = format_note("Mon texte", MOMENT, "maxime")

    assert resultat.startswith("- Mon texte")
    assert "14/08/2026 20:30" in resultat
    assert "depuis la web app" in resultat
    assert "maxime" in resultat


# =====================================================
# Ajout de notes
# =====================================================


def test_note_sur_projet(service: NoteService):
    result = service.add_note(
        "projet",
        "Projet Alpha",
        "Le compositeur fonctionne",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    assert "Le compositeur fonctionne" in contenu
    assert result.kind == "project"


def test_note_sur_tache(service: NoteService):
    result = service.add_note(
        "tache",
        "Tache complete",
        "Avancement correct",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    assert "Avancement correct" in contenu


def test_note_sur_collaborateur(service: NoteService):
    result = service.add_note(
        "collab",
        "Alice",
        "Disponible en septembre",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    assert "Disponible en septembre" in contenu


def test_note_va_dans_la_section_notes(service: NoteService):
    """Et surtout pas dans « Historique », réservé au bot."""
    result = service.add_note(
        "projet",
        "Projet Alpha",
        "Texte de test",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    position_notes = contenu.index("## Notes")
    position_historique = contenu.index("## Historique")
    position_texte = contenu.index("Texte de test")

    assert position_notes < position_texte < position_historique


def test_note_preserve_le_reste_du_fichier(service: NoteService):
    result = service.add_note(
        "tache",
        "Tache complete",
        "Une note",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    assert "due: 2026-08-27T23:04:57+02:00" in contenu
    assert 'platform: "Code"' in contenu
    assert "| Statut        | `active`" in contenu
    assert "- Tâche créée." in contenu


def test_notes_empilees_la_plus_recente_en_premier(
    service: NoteService,
):
    service.add_note(
        "projet",
        "Projet Alpha",
        "Première",
        now=MOMENT,
    )

    result = service.add_note(
        "projet",
        "Projet Alpha",
        "Seconde",
        now=MOMENT,
    )

    contenu = result.path.read_text(encoding="utf-8")

    assert contenu.index("Seconde") < contenu.index("Première")


# =====================================================
# Refus
# =====================================================


def test_type_inconnu(service: NoteService):
    with pytest.raises(NoteError, match="Type inconnu"):
        service.add_note("machin", "Projet Alpha", "texte")


def test_note_vide(service: NoteService):
    with pytest.raises(NoteError, match="vide"):
        service.add_note("projet", "Projet Alpha", "   ")


def test_fiche_introuvable(service: NoteService):
    with pytest.raises(NoteError, match="Aucun projet"):
        service.add_note("projet", "inexistant", "texte")


def test_fiche_ambigue(service: NoteService):
    with pytest.raises(NoteError, match="Plusieurs tâches"):
        service.add_note("tache", "tache", "texte")


def test_section_notes_absente(
    service: NoteService,
    temp_vault: ObsidianVault,
):
    """La tâche minimale n'a pas de section « Notes »."""
    with pytest.raises(NoteError, match="introuvable"):
        service.add_note("tache", "Tache minimale", "texte")
