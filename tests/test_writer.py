"""Garanties du module d'écriture.

Tout se passe dans un Vault temporaire. Le vrai Vault n'est
jamais touché par un test.
"""

from pathlib import Path

import pytest

from core.obsidian.vault import ObsidianVault
from core.obsidian.writer import (
    VaultWriteError,
    VaultWriter,
    format_value,
)


@pytest.fixture
def writer(temp_vault: ObsidianVault) -> VaultWriter:
    return VaultWriter(temp_vault)


@pytest.fixture
def tache(temp_vault: ObsidianVault) -> Path:
    return (
        temp_vault.path
        / "05-Tasks"
        / "Actives"
        / "Tache complete.md"
    )


# =====================================================
# Mise en forme des valeurs
# =====================================================


def test_format_value_simple():
    assert format_value("active") == "active"
    assert format_value("2026-08-14") == "2026-08-14"


def test_format_value_avec_caracteres_speciaux():
    assert format_value("Créer bot : serv") == '"Créer bot : serv"'
    assert format_value("a, b") == '"a, b"'


def test_format_value_mots_reserves_yaml():
    """« no » nu serait relu comme un booléen."""
    assert format_value("no") == '"no"'
    assert format_value("true") == '"true"'


def test_format_value_vide():
    assert format_value(None) == ""
    assert format_value("") == ""


# =====================================================
# Modification chirurgicale du frontmatter
# =====================================================


def test_modifie_uniquement_la_ligne_visee(
    writer: VaultWriter,
    tache: Path,
):
    avant = tache.read_text(encoding="utf-8")

    writer.set_frontmatter_field(tache, "status", "completed")

    apres = tache.read_text(encoding="utf-8")

    lignes_avant = avant.splitlines()
    lignes_apres = apres.splitlines()

    assert len(lignes_avant) == len(lignes_apres)

    differences = [
        (a, b)
        for a, b in zip(lignes_avant, lignes_apres)
        if a != b
    ]

    assert differences == [
        ("status: active", "status: completed")
    ]


def test_preserve_le_format_des_dates(
    writer: VaultWriter,
    tache: Path,
):
    """Le « T » des dates ISO doit survivre.

    C'est la régression que provoquerait un aller-retour PyYAML :
    « due: 2026-08-27T23:04:57+02:00 » deviendrait
    « due: 2026-08-27 23:04:57+02:00 », que le dashboard Obsidian
    ne saurait plus lire.
    """
    writer.set_frontmatter_field(tache, "priority", "low")

    contenu = tache.read_text(encoding="utf-8")

    assert "due: 2026-08-27T23:04:57+02:00" in contenu
    assert "created: 2026-08-13T23:04:57+02:00" in contenu


def test_preserve_les_guillemets_des_autres_champs(
    writer: VaultWriter,
    tache: Path,
):
    writer.set_frontmatter_field(tache, "status", "waiting")

    contenu = tache.read_text(encoding="utf-8")

    assert 'platform: "Code"' in contenu
    assert 'project: "Projet Alpha"' in contenu
    assert "completed:" in contenu
    assert "completed: null" not in contenu


def test_preserve_le_corps_du_document(
    writer: VaultWriter,
    tache: Path,
):
    writer.set_frontmatter_field(tache, "status", "archived")

    contenu = tache.read_text(encoding="utf-8")

    assert "# Tache complete" in contenu
    assert "## Historique" in contenu
    assert "- Tâche créée." in contenu


def test_champ_absent_est_ajoute(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    minimale = (
        temp_vault.path
        / "05-Tasks"
        / "_Inbox"
        / "Tache minimale.md"
    )

    writer.set_frontmatter_field(minimale, "status", "active")

    task = temp_vault.read_task(minimale)

    assert task.status == "active"
    assert "# Tache minimale" in minimale.read_text(
        encoding="utf-8"
    )


def test_valeur_vide(writer: VaultWriter, tache: Path):
    writer.set_frontmatter_field(tache, "completed", None)

    contenu = tache.read_text(encoding="utf-8")

    assert "completed:\n" in contenu


def test_valeur_avec_espaces_est_quotee(
    writer: VaultWriter,
    tache: Path,
):
    writer.set_frontmatter_field(
        tache,
        "collaborator",
        "Me + ZIPZOP",
    )

    data = writer.vault.read_frontmatter(tache)

    assert data["collaborator"] == "Me + ZIPZOP"


# =====================================================
# Refus
# =====================================================


def test_refuse_hors_vault(
    writer: VaultWriter,
    tmp_path: Path,
):
    exterieur = tmp_path.parent / "exterieur.md"
    exterieur.write_text("---\ntype: task\n---\n", encoding="utf-8")

    contenu_avant = exterieur.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="en dehors du Vault"):
        writer.set_frontmatter_field(
            exterieur,
            "status",
            "completed",
        )

    assert exterieur.read_text(encoding="utf-8") == contenu_avant


def test_refuse_fichier_non_markdown(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    autre = temp_vault.path / "note.txt"
    autre.write_text("bonjour", encoding="utf-8")

    with pytest.raises(ValueError, match="Markdown"):
        writer.set_frontmatter_field(autre, "status", "active")

    assert autre.read_text(encoding="utf-8") == "bonjour"


def test_refuse_fichier_inexistant(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    manquant = temp_vault.path / "05-Tasks" / "Fantome.md"

    with pytest.raises(VaultWriteError, match="n'existe pas"):
        writer.set_frontmatter_field(manquant, "status", "active")

    assert not manquant.exists()


def test_refuse_fichier_sans_frontmatter(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    note = temp_vault.path / "02-Projects" / "Projects.md"

    contenu_avant = note.read_text(encoding="utf-8")

    with pytest.raises(VaultWriteError, match="pas de frontmatter"):
        writer.set_frontmatter_field(note, "status", "active")

    assert note.read_text(encoding="utf-8") == contenu_avant


def test_refuse_valeur_sur_plusieurs_lignes(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    """Une liste YAML ne doit pas être décapitée."""
    fichier = temp_vault.path / "05-Tasks" / "Avec liste.md"
    fichier.write_text(
        "---\n"
        "type: task\n"
        "status: active\n"
        "tags:\n"
        "  - alpha\n"
        "  - beta\n"
        "---\n\n"
        "# Avec liste\n",
        encoding="utf-8",
    )

    contenu_avant = fichier.read_text(encoding="utf-8")

    with pytest.raises(VaultWriteError, match="plusieurs"):
        writer.set_frontmatter_field(fichier, "tags", "gamma")

    assert fichier.read_text(encoding="utf-8") == contenu_avant


# =====================================================
# Atomicité et restauration
# =====================================================


def test_aucun_fichier_temporaire_laisse(
    writer: VaultWriter,
    tache: Path,
):
    writer.set_frontmatter_field(tache, "status", "completed")

    restes = list(tache.parent.glob(".*tmp"))

    assert restes == []


def test_restauration_si_relecture_invalide(
    writer: VaultWriter,
    tache: Path,
    monkeypatch,
):
    """Si le résultat est illisible, on remet le fichier d'origine."""
    contenu_avant = tache.read_text(encoding="utf-8")

    def relecture_cassee(self, file_path):
        raise ValueError("frontmatter simulé illisible")

    monkeypatch.setattr(
        type(writer.vault),
        "read_frontmatter",
        relecture_cassee,
    )

    with pytest.raises(VaultWriteError, match="annulée"):
        writer.set_frontmatter_field(tache, "status", "completed")

    assert tache.read_text(encoding="utf-8") == contenu_avant


# =====================================================
# Déplacement
# =====================================================


def test_deplacement(
    writer: VaultWriter,
    tache: Path,
    temp_vault: ObsidianVault,
):
    destination_folder = temp_vault.path / "05-Tasks" / "Terminées"

    contenu_avant = tache.read_text(encoding="utf-8")

    nouveau = writer.move_note(tache, destination_folder)

    assert nouveau.parent == destination_folder
    assert not tache.exists()
    assert nouveau.read_text(encoding="utf-8") == contenu_avant


def test_deplacement_refuse_ecrasement(
    writer: VaultWriter,
    tache: Path,
    temp_vault: ObsidianVault,
):
    destination_folder = temp_vault.path / "05-Tasks" / "Terminées"
    occupant = destination_folder / tache.name
    occupant.write_text("---\ntype: task\n---\n", encoding="utf-8")

    with pytest.raises(VaultWriteError, match="porte déjà ce nom"):
        writer.move_note(tache, destination_folder)

    assert tache.exists()
    assert "type: task" in occupant.read_text(encoding="utf-8")


def test_deplacement_vers_le_meme_dossier(
    writer: VaultWriter,
    tache: Path,
):
    resultat = writer.move_note(tache, tache.parent)

    assert resultat == tache
    assert tache.exists()


def test_deplacement_hors_vault_refuse(
    writer: VaultWriter,
    tache: Path,
    tmp_path: Path,
):
    with pytest.raises(VaultWriteError, match="en dehors du Vault"):
        writer.move_note(tache, tmp_path.parent)

    assert tache.exists()


# =====================================================
# Création
# =====================================================


def test_creation(writer: VaultWriter, temp_vault: ObsidianVault):
    cible = temp_vault.path / "05-Tasks" / "_Inbox" / "Nouvelle.md"

    contenu = (
        "---\ntype: task\nstatus: active\n---\n\n# Nouvelle\n"
    )

    resultat = writer.create_note(cible, contenu)

    assert resultat.exists()
    assert temp_vault.read_task(resultat).status == "active"


def test_creation_refuse_ecrasement(
    writer: VaultWriter,
    tache: Path,
):
    contenu_avant = tache.read_text(encoding="utf-8")

    with pytest.raises(VaultWriteError, match="porte déjà ce nom"):
        writer.create_note(tache, "---\ntype: task\n---\n")

    assert tache.read_text(encoding="utf-8") == contenu_avant


def test_creation_invalide_annulee(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    """Un contenu illisible ne doit pas rester sur le disque."""
    cible = temp_vault.path / "05-Tasks" / "_Inbox" / "Cassee.md"

    with pytest.raises(VaultWriteError):
        writer.create_note(
            cible,
            "---\ntype: task\n  mauvais: [indentation\n---\n",
        )

    assert not cible.exists()


# =====================================================
# Insertion dans une section
# =====================================================


def test_insertion_en_tete_de_section(
    writer: VaultWriter,
    tache: Path,
):
    writer.prepend_to_section(
        tache,
        "## Historique",
        "### 14/08/2026\n\n- Nouvelle entrée.",
    )

    contenu = tache.read_text(encoding="utf-8")

    position_nouvelle = contenu.index("Nouvelle entrée")
    position_ancienne = contenu.index("Tâche créée")

    assert position_nouvelle < position_ancienne
    assert "## Historique" in contenu


def test_insertion_preserve_le_frontmatter(
    writer: VaultWriter,
    tache: Path,
):
    writer.prepend_to_section(
        tache,
        "Historique",
        "- Note ajoutée.",
    )

    contenu = tache.read_text(encoding="utf-8")

    assert "due: 2026-08-27T23:04:57+02:00" in contenu
    assert 'platform: "Code"' in contenu


def test_insertion_section_absente(
    writer: VaultWriter,
    tache: Path,
):
    contenu_avant = tache.read_text(encoding="utf-8")

    with pytest.raises(VaultWriteError, match="introuvable"):
        writer.prepend_to_section(
            tache,
            "## Section Inexistante",
            "- rien",
        )

    assert tache.read_text(encoding="utf-8") == contenu_avant


# =====================================================
# Tableau « Informations »
# =====================================================


def test_table_field_met_a_jour_la_ligne(
    writer: VaultWriter,
    tache: Path,
):
    assert writer.set_table_field(tache, "Statut", "completed")

    contenu = tache.read_text(encoding="utf-8")

    assert "| `completed`" in contenu
    assert "| `active`" not in contenu


def test_table_field_preserve_les_accents_graves(
    writer: VaultWriter,
    tache: Path,
):
    """Statut et Priorité sont en code, Plateforme non."""
    writer.set_table_field(tache, "Priorité", "low")
    writer.set_table_field(tache, "Plateforme", "Discord")

    contenu = tache.read_text(encoding="utf-8")

    assert "`low`" in contenu
    assert "| Plateforme    | Discord" in contenu
    assert "`Discord`" not in contenu


def test_table_field_preserve_l_alignement(
    writer: VaultWriter,
    tache: Path,
):
    """Obsidian aligne les tableaux : il faut garder les colonnes."""
    avant = tache.read_text(encoding="utf-8")

    largeurs_avant = [
        len(ligne)
        for ligne in avant.splitlines()
        if ligne.startswith("| ")
    ]

    writer.set_table_field(tache, "Statut", "waiting")

    apres = tache.read_text(encoding="utf-8")

    largeurs_apres = [
        len(ligne)
        for ligne in apres.splitlines()
        if ligne.startswith("| ")
    ]

    assert largeurs_avant == largeurs_apres


def test_table_field_ligne_absente(
    writer: VaultWriter,
    tache: Path,
):
    contenu_avant = tache.read_text(encoding="utf-8")

    assert not writer.set_table_field(
        tache,
        "Champ Inexistant",
        "valeur",
    )

    assert tache.read_text(encoding="utf-8") == contenu_avant


def test_table_field_note_sans_tableau(
    writer: VaultWriter,
    temp_vault: ObsidianVault,
):
    sans_tableau = (
        temp_vault.path
        / "05-Tasks"
        / "En attente"
        / "Tache attente.md"
    )

    assert not writer.set_table_field(
        sans_tableau,
        "Statut",
        "active",
    )


def test_table_field_preserve_le_frontmatter(
    writer: VaultWriter,
    tache: Path,
):
    writer.set_table_field(tache, "Statut", "archived")

    contenu = tache.read_text(encoding="utf-8")

    assert "due: 2026-08-27T23:04:57+02:00" in contenu
    assert "status: active" in contenu  # inchangé côté frontmatter


# =====================================================
# Visibilité côté Obsidian
# =====================================================


def test_ecriture_rafraichit_l_horodatage(temp_vault, temp_vault_path):
    """Obsidian n'indexe pas ce qu'il ne voit pas changer.

    L'écriture atomique renomme un fichier temporaire caché sur la
    note : sans horodatage rafraîchi, l'index d'Obsidian — donc
    Dataview, donc `05-Tasks/tasks.md` — peut rester sur l'ancienne
    version.
    """
    import os
    import time

    writer = VaultWriter(temp_vault)

    chemin = temp_vault_path / "05-Tasks/Actives/Tache complete.md"

    os.utime(chemin, (0, 0))

    avant = chemin.stat().st_mtime

    writer.set_frontmatter_field(chemin, "priority", "low")

    assert chemin.stat().st_mtime > avant
    assert abs(chemin.stat().st_mtime - time.time()) < 60


def test_creation_rafraichit_aussi_l_horodatage(
    temp_vault,
    temp_vault_path,
):
    import time

    writer = VaultWriter(temp_vault)

    chemin = temp_vault_path / "05-Tasks/Actives/Toute neuve.md"

    writer.create_note(
        chemin,
        "---\ntype: task\nstatus: active\n---\n\n# Toute neuve\n",
    )

    assert abs(chemin.stat().st_mtime - time.time()) < 60


def test_le_temporaire_ne_survit_pas(temp_vault, temp_vault_path):
    """Un « .md.tmp » oublié polluerait le dossier."""
    writer = VaultWriter(temp_vault)

    chemin = temp_vault_path / "05-Tasks/Actives/Tache complete.md"

    writer.set_frontmatter_field(chemin, "priority", "high")

    restes = list(chemin.parent.glob(".*.tmp"))

    assert restes == []


def test_rendre_visible_ne_change_pas_un_octet(temp_vault_path):
    """La parade ne doit jamais devenir un risque de corruption.

    Réécrire les mêmes octets sans troncature garantit qu'une
    interruption laisse le fichier intact.
    """
    import hashlib

    from core.obsidian.writer import rendre_visible

    chemin = temp_vault_path / "05-Tasks/Actives/Tache complete.md"

    avant = chemin.read_bytes()
    empreinte = hashlib.sha256(avant).hexdigest()

    assert rendre_visible(chemin)

    apres = chemin.read_bytes()

    assert apres == avant
    assert hashlib.sha256(apres).hexdigest() == empreinte


def test_rendre_visible_encaisse_un_fichier_absent(temp_vault_path):
    """Une note supprimée entre-temps ne doit rien faire échouer."""
    from core.obsidian.writer import rendre_visible

    assert not rendre_visible(temp_vault_path / "nulle-part.md")


def test_ecriture_produit_un_evenement_sur_la_note(
    temp_vault,
    temp_vault_path,
):
    """C'est ce qui manquait : le renommage atomique ne signalait
    rien sur la note elle-même, donc Obsidian ne réindexait pas."""
    import os

    writer = VaultWriter(temp_vault)

    chemin = temp_vault_path / "05-Tasks/Actives/Tache complete.md"

    os.utime(chemin, (0, 0))

    writer.set_frontmatter_field(chemin, "platform", "Discord")

    # Horodatage rafraîchi ET contenu correct : l'écriture est
    # visible sans avoir été compromise.
    assert chemin.stat().st_mtime > 0

    relu = temp_vault.read_frontmatter(chemin)

    assert relu["platform"] == "Discord"
    assert relu["type"] == "task"


# =====================================================
# Écriture en fin de section (journal)
# =====================================================


@pytest.fixture
def journal(temp_vault: ObsidianVault) -> Path:
    return temp_vault.path / "07-Notes" / "Journal.md"


def test_append_bullet_ajoute_a_la_fin_de_la_section(writer, journal):
    writer.append_bullet_to_section(journal, "## 2026-08-18", "- ajoutee")

    lignes = journal.read_text(encoding="utf-8").splitlines()

    debut = lignes.index("## 2026-08-18")
    fin = lignes.index("## 2026-08-19")

    assert lignes[debut:fin] == [
        "## 2026-08-18",
        "",
        "- rappeler le client",
        "- verifier postgres",
        "- ajoutee",
        "",
    ]


def test_append_bullet_remplace_la_puce_vide_du_gabarit(writer, journal):
    writer.append_bullet_to_section(journal, "## 2026-08-19", "- ajoutee")

    contenu = journal.read_text(encoding="utf-8")

    assert contenu.endswith("## 2026-08-19\n\n- ajoutee\n")


def test_append_bullet_pose_la_ligne_vide_sous_le_titre(
    writer,
    temp_vault_path,
):
    chemin = temp_vault_path / "07-Notes" / "Serree.md"

    chemin.write_text(
        "---\ntype: journal\n---\n\n## 2026-08-20\n",
        encoding="utf-8",
    )

    writer.append_bullet_to_section(chemin, "## 2026-08-20", "- premiere")

    assert chemin.read_text(encoding="utf-8").endswith(
        "## 2026-08-20\n\n- premiere\n"
    )


def test_append_bullet_refuse_une_section_absente(writer, journal):
    with pytest.raises(VaultWriteError):
        writer.append_bullet_to_section(journal, "## 2030-01-01", "- x")


def test_append_bullet_ne_touche_pas_au_preambule(writer, journal):
    avant = journal.read_text(encoding="utf-8")

    writer.append_bullet_to_section(journal, "## 2026-08-18", "- ajoutee")

    apres = journal.read_text(encoding="utf-8")

    entete = avant.split("## 2026-08-18")[0]

    assert apres.startswith(entete)


def test_append_block_ajoute_a_la_fin_du_fichier(writer, journal):
    writer.append_block(journal, "## 2026-08-20\n\n- premiere")

    contenu = journal.read_text(encoding="utf-8")

    assert contenu.endswith("## 2026-08-20\n\n- premiere\n")
    assert contenu.index("## 2026-08-20") > contenu.index("## 2026-08-19")


def test_append_block_conserve_le_frontmatter(writer, journal, temp_vault):
    writer.append_block(journal, "## 2026-08-20\n\n- premiere")

    assert temp_vault.read_frontmatter(journal)["type"] == "journal"


# =====================================================
# Cases à cocher
# =====================================================


@pytest.fixture
def note(temp_vault: ObsidianVault) -> Path:
    return temp_vault.path / "07-Notes" / "Points Alpha.md"


def test_set_checkbox_coche_la_bonne_case(writer, note):
    from core.utils.markdown import lire_cases

    texte, modifiee = writer.set_checkbox(note, 2, True)

    assert texte == "sous-point indente"
    assert modifiee

    cases = lire_cases(note.read_text(encoding="utf-8"))

    assert [case.cochee for case in cases] == [False, True, True]


def test_set_checkbox_conserve_l_indentation(writer, note):
    writer.set_checkbox(note, 2, True)

    assert "  - [x] sous-point indente" in note.read_text(encoding="utf-8")


def test_set_checkbox_ne_change_qu_une_ligne(writer, note):
    avant = note.read_text(encoding="utf-8").splitlines()

    writer.set_checkbox(note, 0, True)

    apres = note.read_text(encoding="utf-8").splitlines()

    assert len(avant) == len(apres)
    assert sum(1 for a, b in zip(avant, apres) if a != b) == 1


def test_set_checkbox_est_idempotent(writer, note):
    contenu = note.read_text(encoding="utf-8")

    texte, modifiee = writer.set_checkbox(note, 1, True)

    assert texte == "relire le texte"
    assert not modifiee
    assert note.read_text(encoding="utf-8") == contenu


def test_set_checkbox_verifie_le_libelle(writer, note):
    with pytest.raises(VaultWriteError) as erreur:
        writer.set_checkbox(note, 0, True, texte_attendu="autre chose")

    assert "ne dit plus la même chose" in str(erreur.value)


def test_set_checkbox_refuse_un_rang_hors_limites(writer, note):
    with pytest.raises(VaultWriteError) as erreur:
        writer.set_checkbox(note, 9, True)

    assert "elle en compte 3" in str(erreur.value)


def test_set_checkbox_sur_une_note_sans_frontmatter(
    writer,
    temp_vault_path,
):
    chemin = temp_vault_path / "07-Notes" / "Brute.md"

    chemin.write_text("# Brute\n\n- [ ] un point\n", encoding="utf-8")

    writer.set_checkbox(chemin, 0, True)

    assert chemin.read_text(encoding="utf-8") == (
        "# Brute\n\n- [x] un point\n"
    )
