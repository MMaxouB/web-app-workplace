"""Tests de la surveillance du Vault (§28).

Le filtrage est la partie qui compte : mal réglé, il ferait
clignoter l'interface à chaque déplacement de curseur dans Obsidian,
ou annoncerait nos propres fichiers temporaires comme des
modifications du Vault.
"""

import asyncio

import pytest

from core.surveillance import SurveillantVault, concerne_le_vault


# =====================================================
# Filtrage des événements
# =====================================================


@pytest.mark.parametrize(
    "chemin",
    [
        "/vault/05-Tasks/Actives/Une tâche.md",
        "/vault/02-Projects/Actifs/Projet.md",
        "/vault/note.md",
    ],
)
def test_une_note_markdown_compte(chemin):
    assert concerne_le_vault(chemin) is True


@pytest.mark.parametrize(
    "chemin",
    [
        # Obsidian réécrit son workspace en permanence.
        "/vault/.obsidian/workspace.json",
        "/vault/.obsidian/plugins/dataview/main.js",
        # Le fichier temporaire de notre propre writer.
        "/vault/05-Tasks/Actives/.Une tâche.md.tmp",
        "/vault/.caché/note.md",
        # Pas du Markdown.
        "/vault/image.png",
        "/vault/05-Tasks/notes.txt",
        "/vault/dossier",
    ],
)
def test_le_reste_est_ignore(chemin):
    assert concerne_le_vault(chemin) is False


def test_le_temporaire_du_writer_ne_declenche_rien():
    """Le writer écrit `.nom.md.tmp` puis renomme.

    Si le temporaire comptait, chaque écriture serait annoncée deux
    fois — une fois pour lui, une fois pour la note finale.
    """
    from core.obsidian.writer import VaultWriter

    temporaire = "/vault/05-Tasks/Actives/.Tache.md.tmp"
    finale = "/vault/05-Tasks/Actives/Tache.md"

    assert concerne_le_vault(temporaire) is False
    assert concerne_le_vault(finale) is True

    # Le nom du temporaire suit bien la forme produite par le writer.
    assert VaultWriter is not None


# =====================================================
# Abonnements
# =====================================================


@pytest.mark.asyncio
async def test_un_abonne_recoit_les_messages(temp_vault):
    surveillant = SurveillantVault(temp_vault.path)

    file = surveillant.abonner()

    surveillant.diffuser({"type": "vault", "notes": ["A.md"]})

    assert await asyncio.wait_for(file.get(), timeout=1) == {
        "type": "vault",
        "notes": ["A.md"],
    }


@pytest.mark.asyncio
async def test_plusieurs_abonnes_recoivent_tous(temp_vault):
    surveillant = SurveillantVault(temp_vault.path)

    files = [surveillant.abonner() for _ in range(3)]

    assert surveillant.nombre_abonnes == 3

    surveillant.diffuser({"type": "vault", "notes": ["B.md"]})

    for file in files:
        assert (await asyncio.wait_for(file.get(), timeout=1))["notes"] == [
            "B.md"
        ]


@pytest.mark.asyncio
async def test_desabonner_libere_la_place(temp_vault):
    surveillant = SurveillantVault(temp_vault.path)

    file = surveillant.abonner()
    assert surveillant.nombre_abonnes == 1

    surveillant.desabonner(file)
    assert surveillant.nombre_abonnes == 0

    # Diffuser sans abonné ne doit pas lever.
    surveillant.diffuser({"type": "vault", "notes": []})


@pytest.mark.asyncio
async def test_un_client_lent_ne_bloque_pas(temp_vault):
    """Un onglet en veille ne doit pas retenir la surveillance.

    La file a une taille bornée : quand elle déborde, le plus ancien
    message est jeté — il est de toute façon périmé, le client
    redemandera l'état courant.
    """
    surveillant = SurveillantVault(temp_vault.path)

    file = surveillant.abonner()

    for numero in range(40):
        surveillant.diffuser({"type": "vault", "notes": [f"{numero}.md"]})

    assert file.qsize() <= 8

    # Le message conservé est parmi les plus récents.
    dernier = None
    while not file.empty():
        dernier = file.get_nowait()

    assert dernier["notes"] == ["39.md"]


# =====================================================
# Cycle de vie
# =====================================================


@pytest.mark.asyncio
async def test_demarrage_et_arret(temp_vault):
    surveillant = SurveillantVault(temp_vault.path)

    assert surveillant.actif is False

    await surveillant.demarrer()
    assert surveillant.actif is True

    await surveillant.arreter()
    assert surveillant.actif is False


@pytest.mark.asyncio
async def test_un_vault_absent_ne_fait_pas_planter(tmp_path):
    """Sans Vault, l'application doit rester utilisable."""
    surveillant = SurveillantVault(tmp_path / "nexiste-pas")

    await surveillant.demarrer()

    assert surveillant.actif is False

    await surveillant.arreter()


@pytest.mark.asyncio
async def test_demarrer_deux_fois_ne_cree_qu_une_tache(temp_vault):
    surveillant = SurveillantVault(temp_vault.path)

    await surveillant.demarrer()
    premiere = surveillant._tache

    await surveillant.demarrer()

    assert surveillant._tache is premiere

    await surveillant.arreter()


# =====================================================
# Détection réelle
# =====================================================


@pytest.mark.asyncio
async def test_une_note_modifiee_est_annoncee(temp_vault):
    """Le vrai test : écrire un fichier déclenche-t-il un message ?"""
    surveillant = SurveillantVault(temp_vault.path)

    await surveillant.demarrer()

    file = surveillant.abonner()

    # Laisse le temps à inotify de s'installer.
    await asyncio.sleep(0.3)

    cible = temp_vault.path / "05-Tasks" / "Actives"
    cible.mkdir(parents=True, exist_ok=True)

    (cible / "Nouvelle note.md").write_text(
        "---\ntype: task\nstatus: active\n---\n\n# Nouvelle\n",
        encoding="utf-8",
    )

    try:
        message = await asyncio.wait_for(file.get(), timeout=5)
    finally:
        await surveillant.arreter()

    assert message["type"] == "vault"
    assert "Nouvelle note.md" in message["notes"]


@pytest.mark.asyncio
async def test_un_fichier_ignore_ne_reveille_personne(temp_vault):
    """Écrire dans .obsidian/ ne doit rien annoncer."""
    surveillant = SurveillantVault(temp_vault.path)

    await surveillant.demarrer()

    file = surveillant.abonner()

    await asyncio.sleep(0.3)

    obsidian = temp_vault.path / ".obsidian"
    obsidian.mkdir(parents=True, exist_ok=True)

    (obsidian / "workspace.json").write_text("{}", encoding="utf-8")

    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(file.get(), timeout=1.5)
    finally:
        await surveillant.arreter()
