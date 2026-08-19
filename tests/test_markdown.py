"""Lecture des cases à cocher et des liens `[[...]]`.

Ce sont les deux briques que le Vault n'écrit que dans le **corps**
des notes : l'avancement d'une note de projet et la navigation d'une
connaissance. Aucun frontmatter ne les porte, il faut donc savoir les
retrouver dans le texte sans rien casser autour.
"""

import pytest

from core.utils.markdown import (
    Case,
    ecrire_case,
    lire_cases,
    lire_liens,
)


# =====================================================
# Cases à cocher
# =====================================================


def test_lit_les_cases_dans_l_ordre():
    cases = lire_cases(
        "## Points\n\n- [ ] premier\n- [x] deuxieme\n- [X] troisieme\n"
    )

    assert [case.texte for case in cases] == [
        "premier",
        "deuxieme",
        "troisieme",
    ]

    assert [case.cochee for case in cases] == [False, True, True]
    assert [case.index for case in cases] == [0, 1, 2]


def test_une_puce_ordinaire_n_est_pas_une_case():
    cases = lire_cases("- une puce\n- [ ] une case\n- une autre puce\n")

    assert len(cases) == 1
    assert cases[0].texte == "une case"


def test_l_indentation_est_conservee():
    cases = lire_cases("- [ ] parent\n  - [x] enfant\n")

    assert cases[0].niveau == 0
    assert cases[1].niveau == 2


def test_les_tirets_alternatifs_sont_acceptes():
    """Obsidian accepte `-`, `*` et `+` pour une même liste."""
    cases = lire_cases("* [ ] etoile\n+ [x] plus\n")

    assert len(cases) == 2
    assert cases[1].cochee


def test_le_depart_saute_le_frontmatter():
    contenu = "---\ntype: note\n---\n\n- [ ] premier\n"

    assert len(lire_cases(contenu, depart=3)) == 1

    # Le rang est le même des deux côtés : le frontmatter ne porte
    # jamais de case, c'est ce qui rend l'index interchangeable
    # entre le corps seul et le fichier entier.
    assert lire_cases(contenu)[0].index == 0


def test_une_note_sans_case_rend_une_liste_vide():
    assert lire_cases("# Titre\n\nDu texte.\n") == []


def test_ecrire_case_ne_change_qu_un_caractere():
    assert ecrire_case("- [ ] texte", True) == "- [x] texte"
    assert ecrire_case("- [x] texte", False) == "- [ ] texte"


def test_ecrire_case_conserve_indentation_et_fin_de_ligne():
    assert ecrire_case("  * [ ]  texte  \n", True) == "  * [x]  texte  \n"
    assert ecrire_case("- [ ] texte\r\n", True) == "- [x] texte\r\n"


def test_ecrire_case_refuse_une_ligne_sans_case():
    with pytest.raises(ValueError):
        ecrire_case("- une puce ordinaire", True)


def test_la_ligne_reperee_est_la_bonne():
    contenu = "# Titre\n\ndu texte\n\n- [ ] la case\n"

    case = lire_cases(contenu)[0]

    assert contenu.splitlines()[case.ligne] == "- [ ] la case"
    assert case == Case(index=0, ligne=4, cochee=False, texte="la case")


# =====================================================
# Liens internes
# =====================================================


def test_lit_les_liens_simples():
    assert lire_liens("voir [[XSS stockee]] et [[ffuf]]") == [
        "XSS stockee",
        "ffuf",
    ]


def test_l_alias_et_l_ancre_sont_ecartes():
    liens = lire_liens("[[Note#Section]] puis [[Note reelle|autre nom]]")

    assert liens == ["Note", "Note reelle"]


def test_les_doublons_ne_comptent_qu_une_fois():
    assert lire_liens("[[ffuf]] ... [[ffuf]]") == ["ffuf"]


def test_un_texte_sans_lien_rend_une_liste_vide():
    assert lire_liens("du texte [pas un lien](http://exemple)") == []
