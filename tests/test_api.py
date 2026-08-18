"""Tests de l'API HTTP.

Ils tournent sur un Vault temporaire, jamais sur le vrai : la
fixture `temp_vault` de conftest.py construit une copie qui reproduit les
particularités du Vault réel (fichier Templater non-YAML, note sans
frontmatter, champs incomplets).
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(temp_vault, monkeypatch):
    """Client HTTP branché sur le Vault temporaire.

    `api.app` lit `VAULT_PATH` à l'import : on remplace donc les
    objets déjà construits plutôt que la constante.
    """
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


# =====================================================
# Santé et tableau de bord
# =====================================================


def test_health_voit_le_vault(client):
    reponse = client.get("/api/health")

    assert reponse.status_code == 200
    assert reponse.json()["existe"] is True


def test_dashboard_repond(client):
    donnees = client.get("/api/dashboard").json()

    assert set(donnees["compteurs"]) == {
        "taches_ouvertes",
        "taches_urgentes",
        "projets_actifs",
        "en_retard",
    }

    assert donnees["progression"]["pourcentage"] >= 0
    assert isinstance(donnees["urgent"], list)


def test_dashboard_ne_compte_que_les_taches_ouvertes(client):
    donnees = client.get("/api/dashboard").json()

    toutes = client.get("/api/tasks").json()["items"]

    attendu = sum(1 for tache in toutes if tache["is_open"])

    assert donnees["compteurs"]["taches_ouvertes"] == attendu


# =====================================================
# Tâches
# =====================================================


def test_liste_des_taches(client):
    donnees = client.get("/api/tasks").json()

    assert donnees["total"] == len(donnees["items"])
    assert donnees["total"] > 0

    premiere = donnees["items"][0]

    for champ in ("id", "name", "status", "is_open", "folder"):
        assert champ in premiere


def test_filtre_par_statut(client):
    donnees = client.get("/api/tasks?status=active").json()

    assert all(
        tache["status"] == "active" for tache in donnees["items"]
    )


def test_filtre_par_priorite(client):
    donnees = client.get("/api/tasks?priority=critical").json()

    assert all(
        tache["priority"] == "critical" for tache in donnees["items"]
    )


def test_open_only_exclut_terminees_et_archivees(client):
    donnees = client.get("/api/tasks?open_only=true").json()

    assert all(tache["is_open"] for tache in donnees["items"])


def test_fiche_tache_contient_le_corps(client):
    liste = client.get("/api/tasks").json()["items"]

    fiche = client.get(f"/api/tasks/{liste[0]['id']}").json()

    assert fiche["name"] == liste[0]["name"]
    assert "body" in fiche


def test_due_libre_ne_fait_pas_planter(client):
    """Le Vault contient des `due: x` : ce n'est pas une erreur."""
    donnees = client.get("/api/tasks").json()

    for tache in donnees["items"]:
        if tache["due"] and not tache["due"][:4].isdigit():
            assert tache["due_date"] is None
            break


# =====================================================
# Projets
# =====================================================


def test_liste_des_projets_avec_progression(client):
    donnees = client.get("/api/projects").json()

    assert donnees["total"] > 0

    for projet in donnees["items"]:
        assert 0 <= projet["progression"]["pourcentage"] <= 100
        assert "taches" in projet


def test_fiche_projet_rattache_ses_taches(client):
    projets = client.get("/api/projects").json()["items"]

    fiche = client.get(f"/api/projects/{projets[0]['id']}").json()

    assert "taches" in fiche
    assert "body" in fiche
    assert isinstance(fiche["collaborateurs"], list)


def test_stats_projet(client):
    projets = client.get("/api/projects").json()["items"]

    stats = client.get(
        f"/api/projects/{projets[0]['id']}/stats"
    ).json()

    assert "progression" in stats
    assert len(stats["priorites"]) == 4

    # Trois statuts, pas quatre : « archived » est écarté des
    # graphiques, une tâche abandonnée ne dit rien de l'avancement.
    assert len(stats["statuts"]) == 3
    assert "Archived" not in {e["libelle"] for e in stats["statuts"]}


# =====================================================
# Ce que les graphiques comptent, et ce qu'ils écartent
# =====================================================


def _cree(client, titre, statut, priorite="medium", plateforme="Code"):
    return client.post(
        "/api/tasks",
        json={
            "title": titre,
            "status": statut,
            "priority": priorite,
            "platform": plateforme,
        },
    ).json()


def test_les_archivees_sortent_de_toutes_les_repartitions(client):
    """Une tâche archivée est abandonnée : elle ne compte nulle part."""
    _cree(client, "Abandonnée", "archived", "critical", "Economy")

    d = client.get("/api/dashboard").json()

    plateformes = {
        e["libelle"]: e["valeur"]
        for e in d["repartitions"]["plateformes"]
    }

    assert plateformes.get("Economy", 0) == 0

    assert "Archived" not in {
        e["libelle"] for e in d["repartitions"]["statuts"]
    }

    # Ni dans la progression, ni dans les échéances.
    total_echeances = sum(
        e["valeur"] for e in d["echeances"]["compteurs"]
    )

    ouvertes = [
        t
        for t in client.get("/api/tasks").json()["items"]
        if t["is_open"]
    ]

    assert total_echeances == len(ouvertes)


def test_les_terminees_sortent_des_repartitions_de_charge(client):
    """Priorités, plateformes et projets ne montrent que le travail restant."""
    _cree(client, "Déjà faite", "completed", "critical", "Economy")

    d = client.get("/api/dashboard").json()

    plateformes = {
        e["libelle"]: e["valeur"]
        for e in d["repartitions"]["plateformes"]
    }

    assert plateformes.get("Economy", 0) == 0

    total_priorites = sum(
        e["valeur"] for e in d["repartitions"]["priorites"]
    )

    # Le Vault n'est pas propre : une tâche peut n'avoir aucune
    # priorité, elle n'entre alors dans aucune catégorie. On compare
    # donc aux seules ouvertes qui en portent une.
    avec_priorite = [
        t
        for t in client.get("/api/tasks").json()["items"]
        if t["is_open"]
        and (t["priority"] or "").lower()
        in ("critical", "high", "medium", "low")
    ]

    assert total_priorites == len(avec_priorite)


def test_l_avancement_compte_bien_les_terminees(client):
    """Le seul axe qui doit les voir : c'est ce qu'il mesure."""
    avant = {
        e["libelle"]: e["valeur"]
        for e in client.get("/api/dashboard").json()["repartitions"][
            "statuts"
        ]
    }

    _cree(client, "Finie pour de bon", "completed")

    apres = {
        e["libelle"]: e["valeur"]
        for e in client.get("/api/dashboard").json()["repartitions"][
            "statuts"
        ]
    }

    assert apres["Completed"] == avant.get("Completed", 0) + 1


def test_la_progression_ignore_les_archivees(client):
    """Archiver une tâche ne doit pas faire chuter le pourcentage."""
    avant = client.get("/api/dashboard").json()["progression"]

    _cree(client, "Sans objet", "archived")

    apres = client.get("/api/dashboard").json()["progression"]

    assert apres["total"] == avant["total"]
    assert apres["pourcentage"] == avant["pourcentage"]


# =====================================================
# Collaborateurs
# =====================================================


def test_liste_des_collaborateurs(client):
    donnees = client.get("/api/collaborators").json()

    for collaborateur in donnees["items"]:
        assert collaborateur["taches_actives"] <= collaborateur["taches"]


# =====================================================
# Recherche
# =====================================================


def test_recherche_vide_ne_leve_pas(client):
    donnees = client.get("/api/search?q=").json()

    assert donnees["total"] == 0


def test_recherche_trouve_une_tache(client):
    taches = client.get("/api/tasks").json()["items"]

    mot = taches[0]["name"].split()[0]

    donnees = client.get(f"/api/search?q={mot}").json()

    assert donnees["total"] > 0


# =====================================================
# Identifiants et garde-fous
# =====================================================


def test_identifiant_illisible_donne_404(client):
    assert client.get("/api/tasks/pas-un-identifiant").status_code == 404


def test_identifiant_hors_du_vault_est_refuse(client):
    """Un identifiant forgé ne doit pas sortir du Vault."""
    import base64

    forge = base64.urlsafe_b64encode(
        b"../../../../etc/passwd"
    ).decode().rstrip("=")

    assert client.get(f"/api/tasks/{forge}").status_code == 404


def test_identifiant_non_markdown_est_refuse(client):
    import base64

    forge = base64.urlsafe_b64encode(
        b"../secret.txt"
    ).decode().rstrip("=")

    assert client.get(f"/api/tasks/{forge}").status_code == 404


def test_projet_demande_sur_route_tache_donne_404(client):
    projets = client.get("/api/projects").json()["items"]

    reponse = client.get(f"/api/tasks/{projets[0]['id']}")

    assert reponse.status_code == 404


def test_les_identifiants_font_l_aller_retour(client):
    """Encoder puis décoder doit redonner exactement la même note."""
    taches = client.get("/api/tasks").json()["items"]

    for tache in taches:
        fiche = client.get(f"/api/tasks/{tache['id']}").json()

        assert fiche["name"] == tache["name"]


# =====================================================
# Fil d'activité (§29)
# =====================================================


def test_activite_agrege_les_historiques(client):
    donnees = client.get("/api/activity").json()

    assert donnees["total"] > 0
    assert "par_genre" in donnees

    premiere = donnees["items"][0]

    for champ in ("quand", "date", "texte", "note", "type", "genre", "id"):
        assert champ in premiere


def test_activite_va_du_plus_recent_au_plus_ancien(client):
    items = client.get("/api/activity?limite=50").json()["items"]

    dates = [item["quand"] for item in items]

    assert dates == sorted(dates, reverse=True)


def test_activite_filtre_les_changements(client):
    tout = client.get("/api/activity?limite=500").json()
    chg = client.get("/api/activity?limite=500&changements=true").json()

    assert chg["total"] <= tout["total"]
    assert all(item["automatique"] for item in chg["items"])
    assert "note" not in chg["par_genre"]


def test_activite_filtre_par_genre(client):
    donnees = client.get("/api/activity?genre=statut&limite=500").json()

    assert all(item["genre"] == "statut" for item in donnees["items"])


def test_activite_filtre_par_type_de_note(client):
    donnees = client.get("/api/activity?type=task&limite=500").json()

    assert all(item["type"] == "task" for item in donnees["items"])


def test_les_identifiants_du_fil_sont_exploitables(client):
    """Chaque entrée doit pouvoir ouvrir sa note."""
    items = client.get("/api/activity?limite=20").json()["items"]

    routes = {
        "task": "tasks",
        "project": "projects",
        "collaborator": "collaborators",
    }

    for item in items[:8]:
        reponse = client.get(f"/api/{routes[item['type']]}/{item['id']}")

        assert reponse.status_code == 200


def test_une_ecriture_apparait_dans_le_fil(client):
    """Le fil suit le Vault, sans stockage à côté."""
    tache = client.get("/api/tasks?status=active").json()["items"][0]

    client.patch(
        f"/api/tasks/{tache['id']}",
        json={"priority": "low"},
    )

    textes = [
        item["texte"]
        for item in client.get(
            "/api/activity?genre=priorite&limite=500"
        ).json()["items"]
    ]

    assert any("à `low`" in texte for texte in textes)


def test_la_limite_est_bornee(client):
    """Une limite absurde ne doit pas tout renvoyer ni planter."""
    assert len(client.get("/api/activity?limite=99999").json()["items"]) <= 500
    assert len(client.get("/api/activity?limite=0").json()["items"]) <= 1


# =====================================================
# Vue graph (§22, §23)
# =====================================================


def test_graph_renvoie_noeuds_et_liens(client):
    g = client.get("/api/graph").json()

    assert g["noeuds"]
    assert "liens" in g
    assert "isoles" in g

    types = {n["type"] for n in g["noeuds"]}

    assert types <= {"task", "project", "collaborator"}

    for noeud in g["noeuds"]:
        for champ in ("id", "type", "nom", "statut", "poids"):
            assert champ in noeud


def test_les_liens_pointent_vers_des_noeuds_existants(client):
    """Un lien orphelin ferait planter la mise en page."""
    g = client.get("/api/graph").json()

    identifiants = {n["id"] for n in g["noeuds"]}

    for lien in g["liens"]:
        assert lien["de"] in identifiants
        assert lien["vers"] in identifiants


def test_le_graph_relie_une_tache_a_son_projet(client):
    g = client.get("/api/graph?inclure_terminees=true").json()

    projets = {
        n["id"]: n["nom"] for n in g["noeuds"] if n["type"] == "project"
    }

    liens_projet = [l for l in g["liens"] if l["genre"] == "projet"]

    assert liens_projet
    assert all(l["vers"] in projets for l in liens_projet)


def test_le_graph_ne_contient_jamais_d_archivees(client):
    """Même en demandant les terminées : une tâche abandonnée n'a plus de liens."""
    _cree(client, "Abandonnée du graphe", "archived")

    for requete in ("/api/graph", "/api/graph?inclure_terminees=true"):
        g = client.get(requete).json()

        noms = {n["nom"] for n in g["noeuds"]}

        assert "Abandonnée du graphe" not in noms


def test_les_terminees_sont_ecartees_par_defaut(client):
    _cree(client, "Finie du graphe", "completed")

    sans = client.get("/api/graph").json()
    avec = client.get("/api/graph?inclure_terminees=true").json()

    assert "Finie du graphe" not in {n["nom"] for n in sans["noeuds"]}
    assert "Finie du graphe" in {n["nom"] for n in avec["noeuds"]}
    assert len(avec["noeuds"]) > len(sans["noeuds"])


def test_une_tache_sans_relation_est_signalee(client):
    """C'est souvent une faute de frappe dans un champ, pas un choix."""
    cree = _cree(client, "Toute seule au monde", "active")

    g = client.get("/api/graph").json()

    assert cree["id"] in g["isoles"]


def test_les_isoles_sont_bien_sans_lien(client):
    g = client.get("/api/graph?inclure_terminees=true").json()

    relies = {l["de"] for l in g["liens"]} | {
        l["vers"] for l in g["liens"]
    }

    for identifiant in g["isoles"]:
        assert identifiant not in relies


def test_le_poids_d_un_projet_compte_ses_taches(client):
    g = client.get("/api/graph?inclure_terminees=true").json()

    for noeud in g["noeuds"]:
        if noeud["type"] != "project":
            continue

        attendu = sum(
            1
            for l in g["liens"]
            if l["genre"] == "projet" and l["vers"] == noeud["id"]
        )

        assert noeud["poids"] == attendu


def test_les_identifiants_du_graph_ouvrent_les_fiches(client):
    g = client.get("/api/graph").json()

    routes = {
        "task": "tasks",
        "project": "projects",
        "collaborator": "collaborators",
    }

    for noeud in g["noeuds"][:10]:
        reponse = client.get(f"/api/{routes[noeud['type']]}/{noeud['id']}")

        assert reponse.status_code == 200
