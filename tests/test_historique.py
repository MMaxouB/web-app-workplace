"""Tests du fil d'activité (§29).

Le parsing est la partie qui compte : deux formats de date coexistent
dans le Vault, les comptes rendus rédigés à la main côtoient les
entrées automatiques, et une note mal formée ne doit jamais faire
échouer la lecture des autres.
"""

import datetime
from pathlib import Path

import pytest

from core.services.historique import (
    Entree,
    extraire_section,
    fusionner,
    genre_de,
    grouper_par_jour,
    lire_entrees,
    parse_titre_date,
)


CHEMIN = Path("/vault/05-Tasks/Actives/Une tache.md")


def entrees_de(corps: str, **kwargs):
    return lire_entrees(
        corps,
        note=kwargs.get("note", "Une tache"),
        type_note=kwargs.get("type_note", "task"),
        chemin=CHEMIN,
    )


# =====================================================
# Lecture des dates
# =====================================================


def test_format_francais_avec_heure():
    lu = parse_titre_date("### 17/08/2026 16:15")

    assert lu is not None
    moment, jour_seul = lu

    assert moment == datetime.datetime(2026, 8, 17, 16, 15)
    assert jour_seul is False


def test_format_iso_sans_heure():
    lu = parse_titre_date("### 2026-08-17")

    assert lu is not None
    moment, jour_seul = lu

    assert moment == datetime.datetime(2026, 8, 17, 0, 0)
    assert jour_seul is True


@pytest.mark.parametrize(
    "titre",
    [
        "### Historique",
        "### Notes",
        "### 31/02/2026",          # date impossible
        "### 2026-13-01",          # mois impossible
        "### pas une date",
        "###",
    ],
)
def test_sous_titre_non_date_est_ignore(titre):
    assert parse_titre_date(titre) is None


# =====================================================
# Extraction de la section
# =====================================================


def test_la_section_s_arrete_au_titre_suivant():
    corps = """# Tache

## Historique

### 17/08/2026 10:00

- Une entrée.

## Notes

- Ceci n'est pas de l'historique.
"""
    lignes = "\n".join(extraire_section(corps))

    assert "Une entrée." in lignes
    assert "pas de l'historique" not in lignes


def test_les_sous_titres_appartiennent_a_la_section():
    corps = "## Historique\n\n### 17/08/2026 10:00\n\n- A\n"

    assert any("###" in l for l in extraire_section(corps))


def test_note_sans_historique():
    assert extraire_section("# Titre\n\n## Notes\n\n- rien\n") == []


# =====================================================
# Lecture des entrées
# =====================================================


def test_plusieurs_puces_sous_une_meme_date():
    corps = """## Historique

### 2026-08-17

- Première.
- Deuxième.
- Troisième.
"""
    entrees = entrees_de(corps)

    assert [e.texte for e in entrees] == [
        "Première.",
        "Deuxième.",
        "Troisième.",
    ]
    assert all(e.jour_seul for e in entrees)


def test_chaque_groupe_garde_sa_date():
    corps = """## Historique

### 17/08/2026 16:15

- Récente.

### 16/08/2026 09:00

- Plus ancienne.
"""
    entrees = entrees_de(corps)

    assert entrees[0].quand == datetime.datetime(2026, 8, 17, 16, 15)
    assert entrees[1].quand == datetime.datetime(2026, 8, 16, 9, 0)


def test_une_puce_avant_toute_date_est_ignoree():
    """Sans sous-titre, une puce n'est datée de rien."""
    corps = "## Historique\n\n- Orpheline.\n\n### 2026-08-17\n\n- Datée.\n"

    assert [e.texte for e in entrees_de(corps)] == ["Datée."]


def test_les_continuations_ne_sont_pas_dupliquees():
    """Une sous-liste indentée appartient à la puce précédente."""
    corps = """## Historique

### 2026-08-17

- Trois bugs trouvés :
  1. Le premier.
  2. Le second.
- Autre entrée.
"""
    entrees = entrees_de(corps)

    assert len(entrees) == 2
    assert entrees[0].texte == "Trois bugs trouvés :"


def test_une_note_sans_historique_ne_donne_rien():
    assert entrees_de("# Titre\n\nDu texte.\n") == []


# =====================================================
# Classement des entrées
# =====================================================


@pytest.mark.parametrize(
    "texte,attendu",
    [
        ("Statut passé de `active` à `completed`.", "statut"),
        ("Priorité passée de `medium` à `high`.", "priorite"),
        ("Champ `project` : `` → `X`.", "champ"),
        ("Délai : `7j` → `24h`.", "echeance"),
        ("Échéance déplacée au 26/08/2026.", "echeance"),
        ("Tâche créée.", "creation"),
        ("Tâche créée depuis Discord.", "creation"),
        ("Fiche créée depuis la web app.", "creation"),
        ("Projet créé.", "creation"),
        ("**M2 terminé et prouvé.** On peut créer un compte…", "note"),
        ("Rien n'est commité — tout est en relecture.", "note"),
    ],
)
def test_classement(texte, attendu):
    assert genre_de(texte) == attendu


def test_automatique_distingue_les_comptes_rendus():
    corps = """## Historique

### 2026-08-17

- Statut passé de `active` à `completed`.
- **Un compte rendu rédigé à la main**, bien plus long.
"""
    entrees = entrees_de(corps)

    assert entrees[0].automatique is True
    assert entrees[1].automatique is False


# =====================================================
# Fusion
# =====================================================


def _entree(quand, jour_seul=False, texte="x"):
    return Entree(
        quand=quand,
        jour_seul=jour_seul,
        texte=texte,
        note="n",
        type_note="task",
        chemin=CHEMIN,
    )


def test_le_fil_va_du_plus_recent_au_plus_ancien():
    fil = fusionner(
        [
            _entree(datetime.datetime(2026, 8, 15, 9, 0), texte="vieille"),
            _entree(datetime.datetime(2026, 8, 17, 9, 0), texte="récente"),
            _entree(datetime.datetime(2026, 8, 16, 9, 0), texte="entre"),
        ]
    )

    assert [e.texte for e in fil] == ["récente", "entre", "vieille"]


def test_a_egalite_le_plus_precis_passe_devant():
    """Une entrée horodatée devance une entrée datée au jour."""
    fil = fusionner(
        [
            _entree(datetime.datetime(2026, 8, 17), True, "jour"),
            _entree(datetime.datetime(2026, 8, 17), False, "minute"),
        ]
    )

    assert [e.texte for e in fil] == ["minute", "jour"]


def test_groupement_par_jour():
    jours = grouper_par_jour(
        fusionner(
            [
                _entree(datetime.datetime(2026, 8, 17, 9, 0)),
                _entree(datetime.datetime(2026, 8, 17, 18, 0)),
                _entree(datetime.datetime(2026, 8, 16, 9, 0)),
            ]
        )
    )

    assert [jour for jour, _ in jours] == [
        datetime.date(2026, 8, 17),
        datetime.date(2026, 8, 16),
    ]
    assert len(jours[0][1]) == 2
