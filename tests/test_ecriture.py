"""Tests des routes d'écriture.

Ils écrivent réellement — donc exclusivement dans le Vault
temporaire construit par `conftest.py`. Le vrai Vault n'est jamais
touché ici.

Deux règles de la web app sont vérifiées de près :

- `DELETE` **archive**, il ne supprime pas ;
- une note modifiée entre l'affichage et l'enregistrement provoque
  un 409, pas un écrasement silencieux.
"""

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(temp_vault, monkeypatch):
    from api import app as module

    from core.obsidian.repository import ObsidianRepository

    monkeypatch.setattr(module, "vault", temp_vault)
    monkeypatch.setattr(
        module,
        "repository",
        ObsidianRepository(temp_vault),
    )
    monkeypatch.setattr(module, "VAULT_PATH", temp_vault.path)

    return TestClient(module.app)


def une_tache(client, **filtres):
    taches = client.get("/api/tasks", params=filtres).json()["items"]

    assert taches, "le Vault de test doit contenir des tâches"

    return taches[0]


# =====================================================
# Métadonnées
# =====================================================


def test_meta_donne_les_valeurs_acceptees(client):
    meta = client.get("/api/meta").json()

    assert "active" in meta["statuts"]
    assert "critical" in meta["priorites"]
    assert "Code" in meta["plateformes"]
    assert "7j" in meta["delais"]

    # Un collaborateur n'a que trois statuts.
    assert "archived" not in meta["statuts_collaborateur"]
    assert len(meta["statuts_collaborateur"]) == 3


# =====================================================
# Création
# =====================================================


def test_creer_une_tache(client):
    reponse = client.post(
        "/api/tasks",
        json={
            "title": "Tâche créée par le test",
            "priority": "high",
            "platform": "Code",
            "project": "Projet Alpha",
            "deadline": "3j",
        },
    )

    assert reponse.status_code == 201

    tache = reponse.json()

    assert tache["name"] == "Tâche créée par le test"
    assert tache["priority"] == "high"
    assert tache["status"] == "active"
    assert tache["folder"] == "Actives"
    assert tache["due_date"] is not None

    # Elle est réellement dans le Vault.
    relue = client.get(f"/api/tasks/{tache['id']}").json()

    assert relue["name"] == tache["name"]
    assert "## Objectif" in relue["body"]


def test_creer_une_tache_sans_nom_est_refuse(client):
    assert client.post("/api/tasks", json={}).status_code == 400


def test_creer_une_tache_priorite_invalide(client):
    reponse = client.post(
        "/api/tasks",
        json={"title": "Peu importe", "priority": "urgentissime"},
    )

    assert reponse.status_code == 400


def test_capture_depose_dans_l_inbox(client):
    reponse = client.post(
        "/api/tasks/capture",
        json={"title": "Idée en passant", "detail": "à creuser"},
    )

    assert reponse.status_code == 201

    tache = reponse.json()

    assert tache["is_inbox"] is True
    assert tache["folder"] == "_Inbox"
    # Une capture est active malgré son dossier : c'est voulu.
    assert tache["status"] == "active"


def test_creer_un_projet(client):
    reponse = client.post(
        "/api/projects",
        json={
            "name": "Projet du test",
            "priority": "low",
            "category": "web",
        },
    )

    assert reponse.status_code == 201

    projet = reponse.json()

    assert projet["name"] == "Projet du test"
    assert projet["status"] == "active"


def test_creer_un_collaborateur(client):
    reponse = client.post(
        "/api/collaborators",
        json={"name": "Testeur", "role": "QA", "discord": "testeur42"},
    )

    assert reponse.status_code == 201
    assert reponse.json()["role"] == "QA"


# =====================================================
# Modification
# =====================================================


def test_changer_la_priorite(client):
    tache = une_tache(client, priority="critical")

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"priority": "low"},
    )

    assert reponse.status_code == 200
    assert reponse.json()["priority"] == "low"


def test_changer_le_statut_deplace_le_fichier(client):
    tache = une_tache(client, status="active")

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"status": "completed"},
    )

    assert reponse.status_code == 200

    modifiee = reponse.json()

    assert modifiee["status"] == "completed"
    assert modifiee["folder"] == "Terminées"
    # Le fichier a bougé : l'identifiant a changé.
    assert modifiee["id"] != tache["id"]
    # Le Vault date les tâches terminées.
    assert modifiee["completed"]


def test_modifier_plusieurs_champs_en_une_fois(client):
    tache = une_tache(client, status="active")

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={
            "priority": "critical",
            "platform": "Cybersecurity",
            "project": "Un autre projet",
        },
    )

    assert reponse.status_code == 200

    modifiee = reponse.json()

    assert modifiee["priority"] == "critical"
    assert modifiee["platform"] == "Cybersecurity"
    assert modifiee["project"] == "Un autre projet"


def test_deadline_recalcule_l_echeance(client):
    tache = une_tache(client, status="active")

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"deadline": "24h"},
    )

    assert reponse.status_code == 200

    modifiee = reponse.json()

    assert modifiee["deadline"] == "24h"
    assert modifiee["due_date"] is not None
    assert modifiee["due"] != tache["due"]


def test_modifier_un_projet(client):
    projets = client.get("/api/projects").json()["items"]

    reponse = client.patch(
        f"/api/projects/{projets[0]['id']}",
        json={"priority": "critical", "category": "cybersecurity"},
    )

    assert reponse.status_code == 200
    assert reponse.json()["priority"] == "critical"


def test_collaborateur_refuse_le_statut_archived(client):
    fiches = client.get("/api/collaborators").json()["items"]

    if not fiches:
        pytest.skip("aucun collaborateur dans le Vault de test")

    reponse = client.patch(
        f"/api/collaborators/{fiches[0]['id']}",
        json={"status": "archived"},
    )

    assert reponse.status_code == 400
    assert "trois statuts" in reponse.json()["detail"]


# =====================================================
# Échéance posée à la date (vue calendrier)
# =====================================================


def test_due_date_pose_la_date_et_deduit_le_libelle(client):
    """Glisser une carte sur un jour du calendrier."""
    import datetime

    tache = une_tache(client, status="active")

    cible = datetime.date.today() + datetime.timedelta(days=9)

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"due_date": cible.isoformat()},
    )

    assert reponse.status_code == 200

    modifiee = reponse.json()

    assert modifiee["due_date"] == cible.isoformat()
    # Le libellé garde le format du Vault, même hors liste proposée.
    assert modifiee["deadline"] == "9j"


def test_due_date_conserve_l_heure_d_origine(client):
    import datetime

    tache = une_tache(client, status="active")

    heure_origine = (tache["due"] or "")[11:19]

    cible = datetime.date.today() + datetime.timedelta(days=4)

    modifiee = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"due_date": cible.isoformat()},
    ).json()

    if heure_origine:
        assert modifiee["due"][11:19] == heure_origine


def test_due_date_dans_le_passe_garde_l_ancien_libelle(client):
    """Un délai négatif ne veut rien dire : « -3j » n'est pas écrit."""
    import datetime

    tache = une_tache(client, status="active")

    ancien = tache["deadline"]

    cible = datetime.date.today() - datetime.timedelta(days=3)

    modifiee = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"due_date": cible.isoformat()},
    ).json()

    assert modifiee["due_date"] == cible.isoformat()
    assert modifiee["deadline"] == (ancien or "")
    assert not modifiee["deadline"].startswith("-")


def test_due_date_illisible_est_refusee(client):
    tache = une_tache(client, status="active")

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"due_date": "un jour peut-être"},
    )

    assert reponse.status_code == 400


def test_les_taches_listees_portent_leur_version(client):
    """Le kanban en a besoin pour détecter un conflit sans relire."""
    items = client.get("/api/tasks").json()["items"]

    assert all(isinstance(t["version"], float) for t in items)


# =====================================================
# Archivage — jamais de suppression
# =====================================================


def test_delete_archive_sans_supprimer(client, temp_vault):
    tache = une_tache(client, status="active")

    avant = len(temp_vault.list_markdown_files())

    reponse = client.delete(f"/api/tasks/{tache['id']}")

    assert reponse.status_code == 200

    archivee = reponse.json()

    assert archivee["status"] == "archived"
    assert archivee["folder"] == "Archives"

    # Le nombre de fichiers n'a pas bougé : rien n'a été supprimé.
    assert len(temp_vault.list_markdown_files()) == avant

    # Et la note est toujours lisible.
    assert client.get(f"/api/tasks/{archivee['id']}").status_code == 200


def test_archiver_deux_fois_est_refuse(client):
    tache = une_tache(client, status="active")

    premiere = client.delete(f"/api/tasks/{tache['id']}").json()

    seconde = client.delete(f"/api/tasks/{premiere['id']}")

    assert seconde.status_code == 400


def test_delete_projet_archive(client, temp_vault):
    projets = client.get("/api/projects").json()["items"]

    avant = len(temp_vault.list_markdown_files())

    reponse = client.delete(f"/api/projects/{projets[0]['id']}")

    assert reponse.status_code == 200
    assert reponse.json()["status"] == "archived"
    assert len(temp_vault.list_markdown_files()) == avant


# =====================================================
# Écritures concurrentes
# =====================================================


def test_version_perimee_refuse_l_ecriture(client):
    """Le cas Obsidian : la note a bougé depuis son affichage."""
    tache = une_tache(client, status="active")

    fiche = client.get(f"/api/tasks/{tache['id']}").json()

    version_affichee = fiche["version"]

    # Quelqu'un modifie la note entre-temps (ici, l'API elle-même).
    time.sleep(1.1)
    client.patch(
        f"/api/tasks/{tache['id']}",
        json={"platform": "Obsidian"},
    )

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"priority": "low", "version": version_affichee},
    )

    assert reponse.status_code == 409
    assert "modifiée ailleurs" in reponse.json()["detail"]


def test_version_a_jour_laisse_passer(client):
    tache = une_tache(client, status="active")

    fiche = client.get(f"/api/tasks/{tache['id']}").json()

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"priority": "low", "version": fiche["version"]},
    )

    assert reponse.status_code == 200


def test_sans_version_l_ecriture_passe(client):
    """La version est optionnelle : sans elle, pas de contrôle."""
    tache = une_tache(client, status="active")

    reponse = client.patch(
        f"/api/tasks/{tache['id']}",
        json={"priority": "medium"},
    )

    assert reponse.status_code == 200


# =====================================================
# Notes libres
# =====================================================


def test_ajouter_une_note_a_une_tache(client):
    tache = une_tache(client)

    reponse = client.post(
        f"/api/tasks/{tache['id']}/notes",
        json={"text": "Une remarque ajoutée depuis le test."},
    )

    assert reponse.status_code == 201

    corps = client.get(f"/api/tasks/{tache['id']}").json()["body"]

    assert "Une remarque ajoutée depuis le test." in corps


def test_note_vide_est_refusee(client):
    tache = une_tache(client)

    reponse = client.post(
        f"/api/tasks/{tache['id']}/notes",
        json={"text": "   "},
    )

    assert reponse.status_code == 400


def test_note_sur_un_genre_inconnu(client):
    tache = une_tache(client)

    reponse = client.post(
        f"/api/chevaux/{tache['id']}/notes",
        json={"text": "hop"},
    )

    assert reponse.status_code == 404


# =====================================================
# Garde-fous
# =====================================================


def test_ecriture_sur_identifiant_forge_est_refusee(client):
    import base64

    forge = base64.urlsafe_b64encode(
        b"../../../../etc/passwd"
    ).decode().rstrip("=")

    assert client.patch(
        f"/api/tasks/{forge}",
        json={"priority": "low"},
    ).status_code == 404

    assert client.delete(f"/api/tasks/{forge}").status_code == 404


def test_le_frontmatter_reste_intact_apres_modification(client):
    """Le format du Vault ne doit pas être réécrit par PyYAML.

    C'est le piège décrit dans le writer : un aller-retour
    safe_load/safe_dump transformerait `due: 2026-08-27T23:04:57+02:00`
    en `due: 2026-08-27 23:04:57+02:00`, et le dashboard Obsidian ne
    saurait plus lire la date.
    """
    tache = une_tache(client, status="active")

    from api.schemas import decode_id
    from api import app as module

    chemin = decode_id(tache["id"], module.VAULT_PATH)

    avant = chemin.read_text(encoding="utf-8")

    client.patch(
        f"/api/tasks/{tache['id']}",
        json={"priority": "low"},
    )

    apres = chemin.read_text(encoding="utf-8")

    def frontmatter(contenu: str) -> list[str]:
        lignes = contenu.splitlines()

        return lignes[1 : lignes.index("---", 1)]

    avant_fm = frontmatter(avant)
    apres_fm = frontmatter(apres)

    # Le tableau du corps et l'historique changent aussi — c'est le
    # comportement voulu. Ce qui est vérifié ici, c'est que dans le
    # frontmatter, seule la ligne `priority:` bouge.
    differentes = [
        (a, b) for a, b in zip(avant_fm, apres_fm) if a != b
    ]

    assert differentes == [("priority: critical", "priority: low")]

    # Et surtout : les dates gardent leur « T ».
    for ligne in apres_fm:
        if ligne.startswith(("due:", "created:")):
            assert "T" in ligne, ligne
