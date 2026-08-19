"""Notes de projet : lecture, rattachement et cases à cocher.

Rappel de la convention : une note n'a ni statut ni échéance, et son
dossier ne dit rien de son avancement. Tout ce qui suit en découle.
"""

import datetime

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import VaultWriteError, VaultWriter
from core.services import notes_projet


@pytest.fixture
def writer(temp_vault: ObsidianVault) -> VaultWriter:
    return VaultWriter(temp_vault)


@pytest.fixture
def service(
    temp_repository: ObsidianRepository,
    writer: VaultWriter,
) -> notes_projet.NoteProjetService:
    return notes_projet.NoteProjetService(temp_repository, writer)


@pytest.fixture
def note(temp_repository: ObsidianRepository):
    return next(
        n for n in temp_repository.get_notes() if n.name == "Points Alpha"
    )


# =====================================================
# Lecture
# =====================================================


def test_les_notes_sont_lues(temp_repository):
    assert {n.name for n in temp_repository.get_notes()} == {
        "Points Alpha",
        "Idees en vrac",
        "Ancienne note",
    }


def test_une_note_du_dossier_archives_se_signale(temp_repository):
    archivee = next(
        n for n in temp_repository.get_notes() if n.name == "Ancienne note"
    )

    assert archivee.is_archived

    vivante = next(
        n for n in temp_repository.get_notes() if n.name == "Points Alpha"
    )

    assert not vivante.is_archived


def test_un_projet_vide_reste_lisible(temp_repository):
    """`project:` sans valeur est légitime : la note ne dépend de rien."""
    libre = next(
        n for n in temp_repository.get_notes() if n.name == "Idees en vrac"
    )

    assert libre.project is None


# =====================================================
# Rattachement au projet
# =====================================================


def test_les_notes_d_un_projet_sont_retrouvees(temp_repository):
    projet = temp_repository.find_project("Projet Alpha")

    noms = {n.name for n in temp_repository.get_notes_for_project(projet)}

    assert noms == {"Points Alpha", "Ancienne note"}


def test_le_rattachement_est_tolerant(temp_repository, temp_vault):
    """Le champ `project` reste du texte libre, comme pour les tâches."""
    chemin = temp_vault.path / "07-Notes" / "Tolerante.md"

    chemin.write_text(
        "---\ntype: note\nproject: projet alpha\n---\n\n# Tolerante\n",
        encoding="utf-8",
    )

    projet = temp_repository.find_project("Projet Alpha")

    noms = {n.name for n in temp_repository.get_notes_for_project(projet)}

    assert "Tolerante" in noms


def test_une_faute_de_frappe_detache_la_note(temp_repository, temp_vault):
    """C'est exactement ce que la vue graph doit rendre visible."""
    chemin = temp_vault.path / "07-Notes" / "Fautive.md"

    chemin.write_text(
        '---\ntype: note\nproject: "Projet Alfa"\n---\n\n# Fautive\n',
        encoding="utf-8",
    )

    projets = temp_repository.get_projects()
    notes = temp_repository.get_notes()

    orphelines = {n.name for n in notes_projet.orphelines(projets, notes)}

    assert "Fautive" in orphelines
    assert "Points Alpha" not in orphelines


# =====================================================
# Points et progression
# =====================================================


def test_les_points_sont_lus(temp_vault, note):
    cases = notes_projet.points(temp_vault.read_body(note.path))

    assert [c.texte for c in cases] == [
        "verifier le rendu",
        "relire le texte",
        "sous-point indente",
    ]

    assert [c.cochee for c in cases] == [False, True, False]


def test_la_progression_compte_les_cases(temp_vault, note):
    cases = notes_projet.points(temp_vault.read_body(note.path))

    avancement = notes_projet.progression(cases)

    assert avancement.termine == 1
    assert avancement.total == 3
    assert avancement.pourcentage == 33


def test_une_note_sans_case_n_est_pas_en_retard():
    """0 sur 0 est exact : il n'y a rien à avancer."""
    avancement = notes_projet.progression([])

    assert avancement.total == 0
    assert avancement.pourcentage == 0
    assert avancement.restant == 0


# =====================================================
# Cocher, décocher
# =====================================================


def test_cocher_un_point(service, temp_vault, note):
    texte, avertissements = service.basculer(note, 0, True)

    assert texte == "verifier le rendu"
    assert avertissements == []

    cases = notes_projet.points(temp_vault.read_body(note.path))

    assert cases[0].cochee
    assert cases[1].cochee
    assert not cases[2].cochee


def test_decocher_un_point(service, temp_vault, note):
    service.basculer(note, 1, False)

    cases = notes_projet.points(temp_vault.read_body(note.path))

    assert not cases[1].cochee


def test_seule_la_ligne_visee_change(service, temp_vault, note):
    avant = note.path.read_text(encoding="utf-8").splitlines()

    service.basculer(note, 0, True)

    apres = note.path.read_text(encoding="utf-8").splitlines()

    differentes = [
        (a, b) for a, b in zip(avant, apres) if a != b
    ]

    # La ligne de la case, et la date de mise à jour du frontmatter.
    assert len(differentes) == 2
    assert ("- [ ] verifier le rendu", "- [x] verifier le rendu") in [
        (a.strip(), b.strip()) for a, b in differentes
    ]


def test_le_libelle_attendu_protege_la_note(service, note):
    """Une note réorganisée entre l'affichage et le clic."""
    with pytest.raises(notes_projet.NoteProjetError) as erreur:
        service.basculer(note, 0, True, texte_attendu="autre chose")

    assert "ne dit plus la même chose" in str(erreur.value)


def test_le_libelle_attendu_est_compare_sans_accents(service, note):
    """La comparaison est tolérante, comme partout ailleurs."""
    texte, _ = service.basculer(
        note,
        0,
        True,
        texte_attendu="VÉRIFIER LE RENDU",
    )

    assert texte == "verifier le rendu"


def test_un_rang_hors_limites_est_refuse(service, note):
    with pytest.raises(notes_projet.NoteProjetError):
        service.basculer(note, 42, True)


def test_recocher_ne_reecrit_rien(service, note):
    """Un double-clic ne doit pas réveiller Obsidian pour rien."""
    service.basculer(note, 0, True)

    avant = note.path.stat().st_mtime_ns
    contenu = note.path.read_text(encoding="utf-8")

    service.basculer(note, 0, True)

    assert note.path.read_text(encoding="utf-8") == contenu
    assert note.path.stat().st_mtime_ns == avant


def test_la_date_de_mise_a_jour_suit(service, temp_vault, note):
    jour = datetime.date(2026, 9, 1)

    service.basculer(note, 0, True, today=jour)

    assert temp_vault.read_note(note.path).mis_a_jour == "2026-09-01"


def test_la_date_n_est_ecrite_qu_une_fois_par_jour(
    service,
    temp_vault,
    note,
):
    jour = datetime.date(2026, 9, 1)

    service.basculer(note, 0, True, today=jour)

    rafraichie = temp_vault.read_note(note.path)

    avant = note.path.stat().st_mtime_ns

    service.basculer(rafraichie, 2, True, today=jour)

    # La case a changé, mais pas le frontmatter : la date y était déjà.
    assert temp_vault.read_note(note.path).mis_a_jour == "2026-09-01"
    assert note.path.stat().st_mtime_ns != avant


def test_une_note_sans_frontmatter_ne_bloque_pas_la_case(
    temp_repository,
    writer,
    temp_vault,
):
    """Le contenu fait foi ; la date n'est qu'un à-côté."""
    chemin = temp_vault.path / "07-Notes" / "Brute.md"

    chemin.write_text("# Brute\n\n- [ ] un point\n", encoding="utf-8")

    from core.obsidian.models import Note

    note = Note(
        path=chemin,
        type="note",
        name="Brute",
        project=None,
        sujet=None,
        created=None,
        mis_a_jour=None,
    )

    service = notes_projet.NoteProjetService(temp_repository, writer)

    texte, avertissements = service.basculer(note, 0, True)

    assert texte == "un point"
    assert avertissements
    assert "mis_a_jour" in avertissements[0]
    assert "- [x] un point" in chemin.read_text(encoding="utf-8")


def test_la_note_reste_intacte_si_l_ecriture_echoue(
    service,
    note,
    monkeypatch,
):
    """La restauration du writer doit couvrir aussi les cases."""
    original = note.path.read_text(encoding="utf-8")

    def relecture_cassee(*args, **kwargs):
        raise VaultWriteError("relecture impossible")

    monkeypatch.setattr(
        service.writer.vault,
        "read_frontmatter",
        relecture_cassee,
    )

    with pytest.raises(notes_projet.NoteProjetError):
        service.basculer(note, 0, True)

    assert note.path.read_text(encoding="utf-8") == original
