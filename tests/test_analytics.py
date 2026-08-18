"""Lectures transversales du Vault : dates, échéances, santé.

Aucun Vault n'est ouvert ici : les modèles sont construits à la
main pour maîtriser les dates, et `now` est toujours passé
explicitement — sinon la suite changerait de résultat selon le
jour où elle tourne.
"""

import datetime
from pathlib import Path

import pytest

from core.obsidian.models import Collaborator, Project, Task
from core.services import analytics


# Un dimanche, pour que la fenêtre de sept jours commence un lundi.
MAINTENANT = datetime.datetime(2026, 8, 16, 14, 30)

AUJOURDHUI = MAINTENANT.date()


def jour(decalage: int) -> str:
    """Échéance ISO située à `decalage` jours d'aujourd'hui."""
    date = AUJOURDHUI + datetime.timedelta(days=decalage)

    return date.isoformat()


def tache(nom: str = "Tache", **overrides) -> Task:
    """Tâche active sans date, à compléter par le test.

    Le chemin découle du nom : plusieurs tâches d'un même test
    doivent avoir des chemins distincts, `journee` les identifie
    par là.
    """
    champs = {
        "path": Path("05-Tasks/Actives") / f"{nom}.md",
        "name": nom,
        "type": "task",
        "status": "active",
        "priority": "medium",
        "platform": "Code",
        "project": "Projet Alpha",
        "collaborator": "Moi",
        "created": None,
        "deadline": None,
        "due": None,
        "completed": None,
    }

    champs.update(overrides)

    return Task(**champs)


def projet(nom: str = "Projet Alpha", **overrides) -> Project:
    champs = {
        "path": Path("02-Projects/Actifs") / f"{nom}.md",
        "type": "project",
        "status": "active",
        "name": nom,
        "category": "software",
        "priority": "high",
        "created": None,
        "deadline": None,
        "repository": None,
    }

    champs.update(overrides)

    return Project(**champs)


def collaborateur(nom: str = "Alice", **overrides) -> Collaborator:
    champs = {
        "path": Path("01-Collaborateurs/Actifs") / f"{nom}.md",
        "type": "collaborator",
        "status": "active",
        "name": nom,
        "role": None,
        "company": None,
        "discord": f"{nom.casefold()}#0001",
        "email": None,
        "github": None,
        "website": None,
        "timezone": None,
        "joined": None,
    }

    champs.update(overrides)

    return Collaborator(**champs)


def noms(taches: list[Task]) -> list[str]:
    return [t.name for t in taches]


# =====================================================
# Dates
# =====================================================


def test_les_deux_formats_de_date_du_vault_sont_lus():
    """Le Vault mélange horodatages Templater et dates nues."""
    assert analytics.parse_date(
        "2026-08-27T23:04:57+02:00"
    ) == datetime.date(2026, 8, 27)

    assert analytics.parse_date("2026-08-25") == datetime.date(
        2026, 8, 25
    )

    assert analytics.parse_date(
        "2026-08-27T23:04:57Z"
    ) == datetime.date(2026, 8, 27)


def test_les_valeurs_libres_du_vault_ne_sont_pas_des_dates():
    """`x`, `X` et `14j` signifient « pas d'échéance ».

    Le Vault les contient vraiment ; les traiter comme des erreurs
    ferait planter chaque écran au lieu d'afficher « sans date ».
    """
    for valeur in ("x", "X", "14j", "1m", "", "   ", None):
        assert analytics.parse_date(valeur) is None


def test_une_date_impossible_ne_leve_pas():
    assert analytics.parse_date("2026-13-45") is None
    assert analytics.parse_date("27/08/2026") is None


def test_aujourd_hui_suit_le_now_fourni():
    assert analytics.aujourd_hui(MAINTENANT) == AUJOURDHUI
    assert analytics.aujourd_hui() == datetime.date.today()


# =====================================================
# Progression
# =====================================================


def test_progression_compte_les_taches_terminees():
    avancement = analytics.progression(
        [
            tache("A", status="completed"),
            tache("B"),
            tache("C"),
            tache("D"),
        ]
    )

    assert avancement.termine == 1
    assert avancement.total == 4
    assert avancement.pourcentage == 25
    assert avancement.restant == 3


def test_les_taches_archivees_sortent_des_deux_cotes_du_ratio():
    """Archiver ne doit rien faire reculer.

    Une tâche archivée n'est ni faite ni à faire : la compter au
    dénominateur ferait chuter un pourcentage sans qu'aucun
    travail n'ait été perdu.
    """
    taches = [
        tache("Faite", status="completed"),
        tache("En cours"),
        tache("Vieille 1", status="archived"),
        tache("Vieille 2", status="archived"),
        tache("Vieille 3", status="archived"),
    ]

    avancement = analytics.progression(taches)

    assert avancement.total == 2
    assert avancement.termine == 1
    assert avancement.pourcentage == 50


def test_progression_sans_tache_ne_divise_pas_par_zero():
    avancement = analytics.progression([])

    assert avancement.total == 0
    assert avancement.pourcentage == 0
    assert avancement.restant == 0


def test_un_lot_entierement_archive_reste_a_zero():
    avancement = analytics.progression(
        [tache("A", status="archived")]
    )

    assert avancement.total == 0
    assert avancement.pourcentage == 0


def test_progression_incoherente_ne_rend_pas_un_restant_negatif():
    avancement = analytics.Progression(termine=5, total=3)

    assert avancement.restant == 0


# =====================================================
# Répartitions
# =====================================================


def test_les_quatre_priorites_sortent_toujours_dans_l_ordre():
    """L'histogramme compare des barres : l'ordre est sa lecture.

    Un niveau à zéro reste affiché, sinon les barres se décalent
    d'un cran d'un rafraîchissement à l'autre.
    """
    taches = [
        tache("A", priority="critical"),
        tache("B", priority="low"),
        tache("C", priority="low"),
    ]

    assert analytics.repartition_priorites(taches) == [
        ("Critical", 1),
        ("High", 0),
        ("Medium", 0),
        ("Low", 2),
    ]


def test_la_repartition_des_priorites_ignore_les_taches_fermees():
    """Une répartition qui compte le passé ne dit rien du reste."""
    taches = [
        tache("Faite", priority="critical", status="completed"),
        tache("Rangee", priority="high", status="archived"),
        tache("Ouverte", priority="low"),
    ]

    assert analytics.repartition_priorites(taches) == [
        ("Critical", 0),
        ("High", 0),
        ("Medium", 0),
        ("Low", 1),
    ]


def test_une_priorite_absente_ou_inconnue_ne_gonfle_aucune_colonne():
    taches = [
        tache("Sans", priority=None),
        tache("Vide", priority=""),
        tache("Exotique", priority="urgentissime"),
    ]

    repartition = analytics.repartition_priorites(taches)

    assert sum(valeur for _, valeur in repartition) == 0


def test_la_repartition_des_statuts_compte_aussi_le_passe():
    taches = [
        tache("A"),
        tache("B", status="waiting"),
        tache("C", status="completed"),
        tache("D", status="archived"),
        tache("E", status="brouillon"),
    ]

    assert analytics.repartition_statuts(taches) == [
        ("Active", 1),
        ("Waiting", 1),
        ("Completed", 1),
        ("Archived", 1),
    ]


def test_les_plateformes_manquantes_sont_regroupees():
    """La plateforme est du texte libre : elle peut être vide."""
    taches = [
        tache("A", platform=None),
        tache("B", platform=""),
        tache("C", platform="   "),
    ]

    assert analytics.repartition_plateformes(taches) == [
        ("Non définie", 3)
    ]


def test_les_plateformes_les_plus_chargees_passent_devant():
    taches = [
        tache("A", platform="Code"),
        tache("B", platform="Code"),
        tache("C", platform="Discord"),
        tache("D", platform="Autre"),
        tache("E", platform="Obsidian", status="completed"),
    ]

    assert analytics.repartition_plateformes(taches) == [
        ("Code", 2),
        ("Autre", 1),
        ("Discord", 1),
    ]


def test_un_projet_sans_tache_ouverte_reste_dans_la_charge():
    """C'est précisément ce que la vue cherche à montrer."""
    projets = [projet("Projet Alpha"), projet("Projet Beta")]

    taches = [
        tache("A", project="Projet Alpha"),
        tache("B", project="Projet Alpha"),
        tache("C", project="Projet Beta", status="completed"),
    ]

    assert analytics.charge_par_projet(projets, taches) == [
        ("Projet Alpha", 2),
        ("Projet Beta", 0),
    ]


def test_la_charge_par_projet_d_un_vault_vide_est_vide():
    assert analytics.charge_par_projet([], []) == []


# =====================================================
# Échéances
# =====================================================


def test_chaque_tache_tombe_dans_sa_fenetre():
    taches = [
        tache("Hier", due=jour(-1)),
        tache("Ce soir", due=jour(0)),
        tache("Demain", due=jour(1)),
        tache("Apres-demain", due=jour(2)),
        tache("Dans une semaine", due=jour(7)),
        tache("Dans huit jours", due=jour(8)),
        tache("Un jour", due="x"),
    ]

    dates = analytics.echeances(taches, MAINTENANT)

    assert noms(dates.en_retard) == ["Hier"]
    assert noms(dates.aujourdhui) == ["Ce soir"]
    assert noms(dates.deux_jours) == ["Demain", "Apres-demain"]
    assert noms(dates.sept_jours) == ["Dans une semaine"]
    assert noms(dates.plus_tard) == ["Dans huit jours"]
    assert noms(dates.sans_echeance) == ["Un jour"]


def test_une_tache_fermee_ne_figure_dans_aucune_fenetre():
    """Une deadline dépassée sur une tâche faite n'alerte plus."""
    taches = [
        tache("Faite", due=jour(-3), status="completed"),
        tache("Rangee", due=jour(-3), status="archived"),
    ]

    dates = analytics.echeances(taches, MAINTENANT)

    assert dates.pressantes == []

    assert all(
        compte == 0 for _, compte in dates.compteurs()
    )


def test_les_pressantes_reunissent_le_retard_et_le_jour_meme():
    taches = [
        tache("Hier", due=jour(-1)),
        tache("Ce soir", due=jour(0)),
        tache("Plus tard", due=jour(9)),
    ]

    dates = analytics.echeances(taches, MAINTENANT)

    assert noms(dates.pressantes) == ["Hier", "Ce soir"]


def test_les_compteurs_gardent_leurs_six_libelles():
    dates = analytics.echeances([], MAINTENANT)

    assert dates.compteurs() == [
        ("En retard", 0),
        ("Aujourd'hui", 0),
        ("48 heures", 0),
        ("7 jours", 0),
        ("Plus tard", 0),
        ("Sans date", 0),
    ]


def test_dans_une_fenetre_les_urgentes_passent_devant():
    """Chaque groupe est trié : la vue affiche le haut de liste."""
    taches = [
        tache("Basse", due=jour(-1), priority="low"),
        tache("Critique", due=jour(-1), priority="critical"),
        tache("Haute", due=jour(-1), priority="high"),
    ]

    dates = analytics.echeances(taches, MAINTENANT)

    assert noms(dates.en_retard) == [
        "Critique",
        "Haute",
        "Basse",
    ]


def test_une_liste_enorme_reste_entierement_repartie():
    taches = [
        tache(f"Tache {index}", due=jour(index % 11 - 3))
        for index in range(600)
    ]

    dates = analytics.echeances(taches, MAINTENANT)

    total = sum(compte for _, compte in dates.compteurs())

    assert total == 600


# =====================================================
# Vue « Aujourd'hui »
# =====================================================


def test_une_tache_en_retard_est_urgente_meme_en_priorite_basse():
    """La décision centrale du module.

    Une deadline dépassée appelle la même réaction qu'une priorité
    critique ; classer cette tâche dans « à faire » la ferait
    disparaître sous les autres.
    """
    taches = [
        tache("Oubliee", priority="low", due=jour(-4)),
        tache("Tranquille", priority="low", due=jour(5)),
    ]

    resultat = analytics.journee(taches, MAINTENANT)

    assert noms(resultat.urgent) == ["Oubliee"]
    assert noms(resultat.a_faire) == ["Tranquille"]


def test_une_echeance_du_jour_rend_urgente_une_tache_moyenne():
    taches = [tache("Ce soir", priority="medium", due=jour(0))]

    resultat = analytics.journee(taches, MAINTENANT)

    assert noms(resultat.urgent) == ["Ce soir"]


def test_en_attente_prend_le_pas_sur_urgent():
    """On ne peut pas agir sur ce qui attend quelqu'un d'autre.

    Même critique et en retard, une tâche `waiting` n'a pas sa
    place dans la liste de ce qu'on peut faire aujourd'hui.
    """
    taches = [
        tache(
            "Bloquee",
            status="waiting",
            priority="critical",
            due=jour(-2),
        )
    ]

    resultat = analytics.journee(taches, MAINTENANT)

    assert noms(resultat.en_attente) == ["Bloquee"]
    assert resultat.urgent == []
    assert resultat.a_faire == []


def test_termine_ne_retient_que_le_jour_meme():
    """Sinon la colonne enfle et ne dit plus rien de la journée."""
    taches = [
        tache("Aujourd hui", status="completed", completed=jour(0)),
        tache("Hier", status="completed", completed=jour(-1)),
        tache("Sans date", status="completed", completed="x"),
    ]

    resultat = analytics.journee(taches, MAINTENANT)

    assert noms(resultat.termine) == ["Aujourd hui"]


def test_termine_est_trie_par_nom_sans_tenir_compte_de_la_casse():
    taches = [
        tache("zeta", status="completed", completed=jour(0)),
        tache("Alpha", status="completed", completed=jour(0)),
    ]

    resultat = analytics.journee(taches, MAINTENANT)

    assert noms(resultat.termine) == ["Alpha", "zeta"]


def test_chaque_tache_ouverte_apparait_dans_une_seule_colonne():
    taches = [
        tache("Retard", priority="low", due=jour(-1)),
        tache("Critique", priority="critical", due=jour(20)),
        tache("Calme", priority="medium", due=jour(4)),
        tache("Bloquee", status="waiting"),
        tache("Sans rien", priority=None),
    ]

    resultat = analytics.journee(taches, MAINTENANT)

    trouvees = (
        noms(resultat.urgent)
        + noms(resultat.a_faire)
        + noms(resultat.en_attente)
    )

    assert sorted(trouvees) == sorted(noms(taches))


def test_une_journee_sans_rien_est_vide():
    assert analytics.journee([], MAINTENANT).vide

    assert not analytics.journee(
        [tache("Quelque chose")],
        MAINTENANT,
    ).vide


def test_une_journee_qui_ne_contient_qu_un_termine_n_est_pas_vide():
    taches = [
        tache("Faite", status="completed", completed=jour(0))
    ]

    assert not analytics.journee(taches, MAINTENANT).vide


@pytest.mark.xfail(
    strict=True,
    reason="BOGUE : Task.is_open compare le statut sans "
    "normaliser la casse, alors que analytics utilise casefold "
    "partout ; une tâche « Completed » est donc à la fois "
    "terminée et à faire",
)
def test_un_statut_en_majuscule_ne_compte_qu_une_fois():
    taches = [
        tache(
            "Majuscule",
            status="Completed",
            completed=jour(0),
        )
    ]

    resultat = analytics.journee(taches, MAINTENANT)

    assert noms(resultat.termine) == ["Majuscule"]
    assert resultat.a_faire == []


# =====================================================
# Activité
# =====================================================


def test_l_activite_va_du_plus_ancien_au_plus_recent():
    mesures = analytics.activite([], MAINTENANT)

    dates = [date for date, _ in mesures]

    assert len(dates) == 7
    assert dates[-1] == AUJOURDHUI
    assert dates[0] == AUJOURDHUI - datetime.timedelta(days=6)
    assert dates == sorted(dates)


def test_creation_et_fin_comptent_chacune_pour_un_mouvement():
    """Ce sont les deux seuls évènements que le Vault date."""
    taches = [
        tache(
            "Expediee",
            status="completed",
            created=jour(0),
            completed=jour(0),
        ),
        tache("Nouvelle", created=jour(-2)),
    ]

    mesures = dict(analytics.activite(taches, MAINTENANT))

    assert mesures[AUJOURDHUI] == 2

    assert mesures[
        AUJOURDHUI - datetime.timedelta(days=2)
    ] == 1


def test_ce_qui_tombe_hors_fenetre_ou_sans_date_est_ignore():
    taches = [
        tache("Ancienne", created=jour(-30)),
        tache("Future", created=jour(3)),
        tache("Illisible", created="14j"),
        tache("Muette", created=None),
    ]

    mesures = analytics.activite(taches, MAINTENANT)

    assert all(compte == 0 for _, compte in mesures)


def test_l_activite_par_jour_nomme_les_jours_de_la_semaine():
    """Le 16 août 2026 est un dimanche : la fenêtre part du lundi."""
    libelles = [
        libelle
        for libelle, _ in analytics.activite_par_jour(
            [],
            MAINTENANT,
        )
    ]

    assert libelles == [
        "Lun",
        "Mar",
        "Mer",
        "Jeu",
        "Ven",
        "Sam",
        "Dim",
    ]


def test_la_heatmap_est_faite_de_semaines_completes():
    grille = analytics.heatmap([], MAINTENANT, semaines=3)

    assert len(grille) == 3
    assert all(len(ligne) == 7 for ligne in grille)


def test_la_derniere_case_de_la_heatmap_est_aujourd_hui():
    """La grille se lit comme un calendrier qui remonte le temps."""
    taches = [tache("Du jour", created=jour(0))]

    grille = analytics.heatmap(taches, MAINTENANT, semaines=3)

    assert grille[-1][-1] == 1
    assert sum(sum(ligne) for ligne in grille) == 1


def test_une_fenetre_vide_ne_leve_pas():
    assert analytics.activite([], MAINTENANT, jours=0) == []
    assert analytics.heatmap([], MAINTENANT, semaines=0) == []


# =====================================================
# Santé
# =====================================================

DOMAINES = ["Projets", "Tâches", "Deadlines", "Collaborateurs"]


def test_la_sante_rend_toujours_ses_quatre_indicateurs():
    """Un domaine muet laisserait croire qu'il n'existe pas."""
    for donnees in (
        ([], [], []),
        (
            [projet("Projet Alpha")],
            [tache("Retard", due=jour(-1), priority="critical")],
            [collaborateur("Alice", status="waiting")],
        ),
    ):
        indicateurs = analytics.sante(*donnees, now=MAINTENANT)

        assert [i.domaine for i in indicateurs] == DOMAINES

        assert all(i.detail for i in indicateurs)


def test_un_vault_vide_est_declare_sain():
    indicateurs = analytics.sante([], [], [], now=MAINTENANT)

    assert all(i.niveau == analytics.BON for i in indicateurs)

    assert analytics.niveau_global(indicateurs) == analytics.BON


def test_une_echeance_depassee_rend_les_deadlines_critiques():
    indicateurs = analytics.sante(
        [projet()],
        [tache("Retard", due=jour(-1))],
        [],
        now=MAINTENANT,
    )

    deadlines = indicateurs[2]

    assert deadlines.niveau == analytics.CRITIQUE
    assert "1" in deadlines.detail


def test_une_echeance_du_jour_n_est_qu_une_attention():
    indicateurs = analytics.sante(
        [projet()],
        [tache("Ce soir", due=jour(0))],
        [],
        now=MAINTENANT,
    )

    assert indicateurs[2].niveau == analytics.ATTENTION


def test_trop_de_taches_critiques_font_basculer_les_taches():
    """Seuils bas assumés : c'est un workspace personnel."""
    def lot(nombre: int) -> list[Task]:
        return [
            tache(f"Critique {index}", priority="critical")
            for index in range(nombre)
        ]

    def niveau(nombre: int) -> str:
        return analytics.sante(
            [projet()],
            lot(nombre),
            [],
            now=MAINTENANT,
        )[1].niveau

    assert niveau(2) == analytics.BON
    assert niveau(3) == analytics.ATTENTION
    assert niveau(6) == analytics.CRITIQUE


def test_un_collaborateur_en_attente_est_signale():
    indicateurs = analytics.sante(
        [projet()],
        [tache("A")],
        [
            collaborateur("Alice", status="waiting"),
            collaborateur("Bob"),
        ],
        now=MAINTENANT,
    )

    assert indicateurs[3].niveau == analytics.ATTENTION


def test_le_niveau_global_remonte_le_pire():
    indicateurs = [
        analytics.Indicateur("Projets", analytics.BON, "rien"),
        analytics.Indicateur(
            "Tâches",
            analytics.CRITIQUE,
            "beaucoup",
        ),
        analytics.Indicateur(
            "Deadlines",
            analytics.ATTENTION,
            "un peu",
        ),
    ]

    assert (
        analytics.niveau_global(indicateurs) == analytics.CRITIQUE
    )


def test_le_niveau_global_sans_indicateur_reste_bon():
    assert analytics.niveau_global([]) == analytics.BON


# =====================================================
# Projets sans tâche
# =====================================================


def test_un_projet_dont_tout_est_termine_est_signale():
    projets = [projet("Projet Alpha"), projet("Projet Beta")]

    taches = [
        tache("A", project="Projet Alpha"),
        tache("B", project="Projet Beta", status="completed"),
        tache("C", project="Projet Beta", status="archived"),
    ]

    orphelins = analytics.projets_sans_tache(projets, taches)

    assert [p.name for p in orphelins] == ["Projet Beta"]


def test_seuls_les_projets_actifs_sont_concernes():
    """Un projet terminé sans tâche ouverte est dans son état normal."""
    projets = [
        projet("Fini", status="completed"),
        projet("Range", status="archived"),
        projet("Attente", status="waiting"),
    ]

    assert analytics.projets_sans_tache(projets, []) == []


def test_le_rattachement_tolere_le_nom_de_fichier():
    """Le champ `project` d'une tâche est saisi à la main.

    « AI-powered video editor » doit retrouver le projet stocké
    dans « AI-Powered Video Editor.md », sinon le projet serait
    signalé abandonné alors qu'il travaille.
    """
    projets = [
        projet(
            "AI-Powered Video Editor",
            name="AI Video Editor",
        )
    ]

    taches = [
        tache("A", project="AI-powered video editor")
    ]

    assert analytics.projets_sans_tache(projets, taches) == []


# =====================================================
# Incohérences
# =====================================================


def vault_propre():
    """Un Vault sans rien à corriger."""
    projets = [projet("Projet Alpha")]

    taches = [
        tache(
            "Bien remplie",
            project="Projet Alpha",
            priority="high",
            due=jour(3),
        )
    ]

    collaborateurs = [collaborateur("Alice")]

    return projets, taches, collaborateurs


def test_un_vault_propre_ne_produit_aucun_probleme():
    """Une liste vide, surtout pas une page de zéros.

    Afficher « 0 tâche sans projet » sept fois de suite noierait
    le seul cas qui compte : quand il y a quelque chose à corriger.
    """
    projets, taches, collaborateurs = vault_propre()

    assert (
        analytics.problemes(
            projets,
            taches,
            collaborateurs,
            now=MAINTENANT,
        )
        == []
    )


def test_un_vault_vide_ne_produit_aucun_probleme():
    assert analytics.problemes([], [], [], now=MAINTENANT) == []


def test_chaque_defaut_a_son_entree():
    projets = [projet("Projet Alpha"), projet("Projet Vide")]

    taches = [
        tache(
            "Retard",
            project="Projet Alpha",
            priority="high",
            due=jour(-1),
        ),
        tache(
            "Capture",
            path=Path("05-Tasks/_Inbox/Capture.md"),
            project="Projet Alpha",
            priority="low",
            due=jour(1),
        ),
        tache(
            "Sans projet",
            project="  ",
            priority="low",
            due=jour(1),
        ),
        tache(
            "Sans priorite",
            project="Projet Alpha",
            priority=None,
            due=jour(1),
        ),
        tache(
            "Sans echeance",
            project="Projet Alpha",
            priority="low",
            due="x",
        ),
    ]

    collaborateurs = [collaborateur("Bob", discord=None)]

    detectes = analytics.problemes(
        projets,
        taches,
        collaborateurs,
        now=MAINTENANT,
    )

    assert [probleme.cle for probleme in detectes] == [
        "retard",
        "inbox",
        "sans_projet",
        "sans_priorite",
        "sans_echeance",
        "projets_sans_tache",
        "collabs_sans_discord",
    ]


def test_chaque_probleme_porte_un_conseil_et_ses_elements():
    """Une liste de défauts sans correction ne fait que culpabiliser."""
    detectes = analytics.problemes(
        [],
        [tache("Retard", due=jour(-1))],
        [],
        now=MAINTENANT,
    )

    (retard,) = detectes

    assert retard.titre
    assert retard.conseil
    assert retard.elements == ["Retard"]
    assert retard.total == 1


def test_une_priorite_inconnue_vaut_une_priorite_absente():
    detectes = analytics.problemes(
        [],
        [
            tache(
                "Exotique",
                priority="urgentissime",
                due=jour(2),
            )
        ],
        [],
        now=MAINTENANT,
    )

    assert [probleme.cle for probleme in detectes] == [
        "sans_priorite"
    ]


def test_les_taches_fermees_ne_sont_jamais_reprochees():
    taches = [
        tache(
            "Faite",
            status="completed",
            project=None,
            priority=None,
            due=jour(-5),
        ),
        tache(
            "Rangee",
            status="archived",
            project=None,
            priority=None,
            due="x",
        ),
    ]

    assert (
        analytics.problemes([], taches, [], now=MAINTENANT) == []
    )


def test_un_collaborateur_termine_n_a_plus_besoin_de_discord():
    """Il ne sera plus contacté : lui réclamer un pseudo est du bruit."""
    collaborateurs = [
        collaborateur("Parti", status="completed", discord=None),
        collaborateur("Actif", discord=None),
    ]

    detectes = analytics.problemes(
        [],
        [],
        collaborateurs,
        now=MAINTENANT,
    )

    (probleme,) = detectes

    assert probleme.elements == ["Actif"]


def test_un_nom_tres_long_est_conserve_entier():
    """Tronquer est le travail de l'affichage, pas de l'analyse."""
    nom = "T" * 150

    detectes = analytics.problemes(
        [],
        [tache(nom, due=jour(-1), priority="high")],
        [],
        now=MAINTENANT,
    )

    assert detectes[0].elements == [nom]


def test_beaucoup_de_taches_sales_restent_toutes_listees():
    taches = [
        tache(f"Sale {index}", priority=None, due="x")
        for index in range(400)
    ]

    detectes = {
        probleme.cle: probleme.total
        for probleme in analytics.problemes(
            [],
            taches,
            [],
            now=MAINTENANT,
        )
    }

    assert detectes["sans_priorite"] == 400
    assert detectes["sans_echeance"] == 400
