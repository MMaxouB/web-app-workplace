"""Navigation dans la base de connaissances.

Tout se passe sur le Vault temporaire, qui reproduit les quatre cas
réels : une note complète, une note dont le `domaine:` ne correspond
pas à son dossier, une note sans champ de rangement du tout, et une
note d'un domaine sans sous-dossier.
"""

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault
from core.services import connaissances


@pytest.fixture
def savoirs(temp_repository: ObsidianRepository):
    return temp_repository.get_knowledge()


# =====================================================
# Lecture
# =====================================================


def test_les_connaissances_sont_lues(savoirs):
    assert {note.name for note in savoirs} == {
        "XSS stockee",
        "ffuf",
        "Modele OSI",
        "Ports courants",
    }


def test_le_nom_du_fichier_fait_le_titre(savoirs):
    """La convention interdit un champ `name:` dans le frontmatter."""
    for note in savoirs:
        assert note.name == note.path.stem
        assert note.filename == note.name


def test_les_tags_sont_lus_tels_qu_ecrits(savoirs):
    xss = next(n for n in savoirs if n.name == "XSS stockee")

    assert xss.tags == ("xss", "dom", "bypass", "web")


def test_un_champ_tags_vide_ne_fait_pas_planter(savoirs):
    """`tags:` sans valeur est courant et n'est pas une erreur."""
    osi = next(n for n in savoirs if n.name == "Modele OSI")

    assert osi.tags == ()


def test_les_templates_sont_exclus(temp_repository):
    for note in temp_repository.get_knowledge():
        assert "99-Templates" not in note.path.parts


# =====================================================
# Où la note est rangée
# =====================================================


def test_le_domaine_declare_fait_foi(savoirs, temp_vault):
    xss = next(n for n in savoirs if n.name == "XSS stockee")

    assert connaissances.domaine_de(xss, temp_vault.path) == "Cybersecurity"
    assert connaissances.sujet_de(xss, temp_vault.path) == "Web"


def test_le_dossier_prend_le_relais_quand_le_champ_manque(
    savoirs,
    temp_vault,
):
    """Une note au frontmatter incomplet reste navigable."""
    ports = next(n for n in savoirs if n.name == "Ports courants")

    assert ports.domaine is None
    assert connaissances.domaine_de(ports, temp_vault.path) == "References"
    assert connaissances.sujet_de(ports, temp_vault.path) == ""


def test_un_domaine_sans_sous_dossier_n_a_pas_de_sujet(
    savoirs,
    temp_vault,
):
    ports = next(n for n in savoirs if n.name == "Ports courants")

    assert connaissances.sujet_de(ports, temp_vault.path) == ""


def test_le_dossier_incoherent_est_signale(savoirs, temp_vault):
    """Le contrôle Dataview des conventions, ramené au code."""
    osi = next(n for n in savoirs if n.name == "Modele OSI")

    assert osi.domaine == "Cybersecurity"
    assert "Concepts" in osi.path.parts
    assert not connaissances.dossier_coherent(osi, temp_vault.path)

    xss = next(n for n in savoirs if n.name == "XSS stockee")

    assert connaissances.dossier_coherent(xss, temp_vault.path)


def test_une_note_hors_de_la_base_ne_fait_pas_planter(
    savoirs,
    temp_vault,
    tmp_path,
):
    """Le Vault n'est pas propre : une connaissance égarée reste lue."""
    egaree = savoirs[0].__class__(
        path=temp_vault.path / "05-Tasks" / "Egaree.md",
        type="knowledge",
        name="Egaree",
        categorie="concept",
        domaine=None,
        sujet=None,
        maturite="graine",
        tags=(),
        source=None,
        created=None,
        mis_a_jour=None,
    )

    assert connaissances.segments(egaree, temp_vault.path) == ()
    assert (
        connaissances.domaine_de(egaree, temp_vault.path)
        == connaissances.SANS_DOMAINE
    )


# =====================================================
# Arborescence
# =====================================================


def test_l_arborescence_suit_les_domaines(savoirs, temp_vault):
    branches = connaissances.arborescence(savoirs, temp_vault.path)

    par_nom = {branche.domaine: branche for branche in branches}

    assert par_nom["Cybersecurity"].total == 2
    assert par_nom["Outils"].total == 1
    assert par_nom["References"].total == 1


def test_les_sujets_portent_leurs_compteurs(savoirs, temp_vault):
    branches = connaissances.arborescence(savoirs, temp_vault.path)

    cyber = next(b for b in branches if b.domaine == "Cybersecurity")

    # « Modele OSI » déclare Cybersecurity sans sujet : elle se range
    # donc sous le domaine, sans sous-dossier.
    assert {(r.sujet, r.total) for r in cyber.sujets} == {
        ("Web", 1),
        ("", 1),
    }


def test_l_arborescence_est_vide_sans_connaissance(temp_vault):
    assert connaissances.arborescence([], temp_vault.path) == []


def test_sans_domaine_ferme_la_marche(savoirs, temp_vault):
    egaree = savoirs[0].__class__(
        path=temp_vault.path / "05-Tasks" / "Egaree.md",
        type="knowledge",
        name="Egaree",
        categorie=None,
        domaine=None,
        sujet=None,
        maturite=None,
        tags=(),
        source=None,
        created=None,
        mis_a_jour=None,
    )

    branches = connaissances.arborescence(
        [*savoirs, egaree],
        temp_vault.path,
    )

    assert branches[-1].domaine == connaissances.SANS_DOMAINE


# =====================================================
# Filtres
# =====================================================


def test_filtre_par_domaine(savoirs, temp_vault):
    retenues = connaissances.filtrer(
        savoirs,
        temp_vault.path,
        domaine="Cybersecurity",
    )

    assert {n.name for n in retenues} == {"XSS stockee", "Modele OSI"}


def test_filtre_par_categorie_et_maturite(savoirs, temp_vault):
    assert [
        n.name
        for n in connaissances.filtrer(
            savoirs,
            temp_vault.path,
            categorie="outil",
        )
    ] == ["ffuf"]

    assert {
        n.name
        for n in connaissances.filtrer(
            savoirs,
            temp_vault.path,
            maturite="stable",
        )
    } == {"XSS stockee", "Ports courants"}


def test_le_filtre_par_tag_est_tolerant(savoirs, temp_vault):
    """Un tag saisi avec accents et majuscules doit retrouver le sien."""
    retenues = connaissances.filtrer(savoirs, temp_vault.path, tag="XSS")

    assert [n.name for n in retenues] == ["XSS stockee"]


def test_les_filtres_se_cumulent(savoirs, temp_vault):
    retenues = connaissances.filtrer(
        savoirs,
        temp_vault.path,
        domaine="Cybersecurity",
        maturite="stable",
    )

    assert [n.name for n in retenues] == ["XSS stockee"]


def test_un_filtre_vide_ne_filtre_rien(savoirs, temp_vault):
    assert connaissances.filtrer(
        savoirs,
        temp_vault.path,
        domaine="",
        tag=None,
    ) == savoirs


# =====================================================
# Tris et compteurs
# =====================================================


def test_le_tri_suit_les_dossiers(savoirs, temp_vault):
    noms = [n.name for n in connaissances.trier(savoirs, temp_vault.path)]

    assert noms == [
        "Modele OSI",
        "XSS stockee",
        "ffuf",
        "Ports courants",
    ]


def test_les_tags_sont_comptes_du_plus_frequent_au_moins(savoirs):
    comptes = dict(connaissances.compter_tags(savoirs))

    assert comptes["web"] == 2
    assert comptes["xss"] == 1

    valeurs = [total for _, total in connaissances.compter_tags(savoirs)]

    assert valeurs == sorted(valeurs, reverse=True)


def test_les_variantes_d_ecriture_d_un_tag_se_rejoignent(savoirs):
    variante = savoirs[0].__class__(
        path=savoirs[0].path,
        type="knowledge",
        name="Variante",
        categorie=None,
        domaine=None,
        sujet=None,
        maturite=None,
        tags=("XSS", "Élévation"),
        source=None,
        created=None,
        mis_a_jour=None,
    )

    comptes = dict(connaissances.compter_tags([*savoirs, variante]))

    assert comptes["xss"] == 2


def test_compter_ignore_les_valeurs_absentes(savoirs):
    categories = dict(
        connaissances.compter(
            savoirs,
            connaissances.CATEGORIES,
            "categorie",
        )
    )

    assert categories == {
        "technique": 1,
        "outil": 1,
        "concept": 1,
        "reference": 1,
    }


def test_compter_range_les_valeurs_connues_d_abord(savoirs, temp_vault):
    maturites = [
        libelle
        for libelle, _ in connaissances.compter(
            savoirs,
            connaissances.MATURITES,
            "maturite",
        )
    ]

    assert maturites == ["graine", "brouillon", "stable"]


# =====================================================
# Recherche transversale
# =====================================================


def test_la_recherche_trouve_une_connaissance(temp_repository):
    resultats = temp_repository.search("xss")

    assert [n.name for n in resultats.knowledge] == ["XSS stockee"]


def test_la_recherche_trouve_par_tag(temp_repository):
    resultats = temp_repository.search("fuzzing")

    assert [n.name for n in resultats.knowledge] == ["ffuf"]


def test_les_connaissances_comptent_dans_le_total(temp_repository):
    resultats = temp_repository.search("xss")

    assert resultats.total == (
        len(resultats.projects)
        + len(resultats.tasks)
        + len(resultats.collaborators)
        + len(resultats.knowledge)
        + len(resultats.notes)
    )


def test_une_recherche_sans_resultat_reste_vide(
    temp_vault: ObsidianVault,
):
    repository = ObsidianRepository(temp_vault)

    resultats = repository.search("zzzzz introuvable")

    assert resultats.is_empty
