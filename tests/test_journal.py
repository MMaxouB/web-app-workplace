"""Journal de capture rapide : lecture et écriture.

Le fichier temporaire reproduit le vrai : un préambule, une règle
horizontale, puis une section par jour du plus ancien au plus
récent — avec la puce vide que dépose le gabarit du jour.
"""

import datetime

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.writer import VaultWriter
from core.services import journal


@pytest.fixture
def service(temp_repository: ObsidianRepository) -> journal.JournalService:
    return journal.JournalService(
        temp_repository,
        VaultWriter(temp_repository.vault),
    )


@pytest.fixture
def chemin(service: journal.JournalService):
    return service.chemin()


LE_18 = datetime.datetime(2026, 8, 18, 10, 0)
LE_19 = datetime.datetime(2026, 8, 19, 10, 0)
LE_20 = datetime.datetime(2026, 8, 20, 10, 0)


# =====================================================
# Localisation
# =====================================================


def test_le_journal_est_trouve_par_son_type(chemin):
    """Les conventions promettent que rien ne dépend de son nom."""
    assert chemin.name == "Journal.md"
    assert chemin.parent.name == "07-Notes"


def test_un_journal_renomme_reste_trouve(service, chemin):
    renomme = chemin.parent / "Journal 2026.md"

    chemin.rename(renomme)

    assert service.chemin() == renomme


def test_sans_journal_l_erreur_est_explicite(service, chemin):
    chemin.unlink()

    with pytest.raises(journal.JournalError) as erreur:
        service.chemin()

    assert "type: journal" in str(erreur.value)


def test_aucun_fichier_n_est_cree(service, chemin):
    """La web app n'invente pas une note qu'on ne lui a pas demandée."""
    chemin.unlink()

    with pytest.raises(journal.JournalError):
        service.capturer("une ligne")

    assert not chemin.exists()


# =====================================================
# Lecture
# =====================================================


def test_les_journees_sont_decoupees(service):
    jours = service.jours()

    assert [jour.titre for jour in jours] == ["2026-08-19", "2026-08-18"]


def test_les_journees_sont_rendues_de_la_plus_recente(service):
    dates = [jour.date for jour in service.jours() if jour.date]

    assert dates == sorted(dates, reverse=True)


def test_les_lignes_d_une_journee_sont_lues(service):
    hier = next(j for j in service.jours() if j.titre == "2026-08-18")

    assert hier.lignes == ["rappeler le client", "verifier postgres"]


def test_la_puce_vide_du_gabarit_n_est_pas_une_ligne(service):
    aujourdhui = next(
        j for j in service.jours() if j.titre == "2026-08-19"
    )

    assert aujourdhui.lignes == []


def test_le_preambule_n_est_pas_du_journal():
    """Le titre, la note d'usage et la règle horizontale sont ignorés."""
    jours = journal.lire(
        "# Journal\n\nDu mode d'emploi.\n\n---\n\n## 2026-08-18\n\n- une ligne\n"
    )

    assert len(jours) == 1
    assert jours[0].lignes == ["une ligne"]


def test_un_titre_qui_n_est_pas_une_date_reste_affiche():
    jours = journal.lire("## Notes en vrac\n\n- une ligne\n")

    assert jours[0].titre == "Notes en vrac"
    assert jours[0].date is None
    assert jours[0].lignes == ["une ligne"]


def test_les_journees_sans_date_ferment_la_marche():
    jours = journal.recents_d_abord(
        journal.lire(
            "## Sans date\n\n- a\n\n## 2026-08-18\n\n- b\n"
        )
    )

    assert [jour.titre for jour in jours] == ["2026-08-18", "Sans date"]


def test_une_ligne_indentee_prolonge_la_precedente():
    jours = journal.lire("## 2026-08-18\n\n- une idee\n  suite de l'idee\n")

    assert jours[0].lignes == ["une idee\nsuite de l'idee"]


def test_un_texte_libre_n_est_pas_perdu():
    jours = journal.lire("## 2026-08-18\n\n- une puce\nune ligne sans puce\n")

    assert jours[0].lignes == ["une puce", "une ligne sans puce"]


def test_un_titre_de_niveau_1_referme_la_journee():
    jours = journal.lire("## 2026-08-18\n\n- dedans\n\n# Autre\n\n- dehors\n")

    assert jours[0].lignes == ["dedans"]
    assert len(jours) == 1


# =====================================================
# Capture
# =====================================================


def test_capture_dans_une_journee_existante(service, chemin):
    service.capturer("rappeler le devis", now=LE_18)

    jours = service.jours()
    hier = next(j for j in jours if j.titre == "2026-08-18")

    assert hier.lignes[-1] == "rappeler le devis"
    assert len(jours) == 2


def test_capture_ouvre_une_journee_absente(service):
    service.capturer("premier jour", now=LE_20)

    jours = service.jours()

    assert jours[0].titre == "2026-08-20"
    assert jours[0].lignes == ["premier jour"]
    assert len(jours) == 3


def test_la_nouvelle_journee_va_a_la_fin_du_fichier(service, chemin):
    """`Ctrl + Fin` doit amener là où l'on écrit."""
    service.capturer("premier jour", now=LE_20)

    contenu = chemin.read_text(encoding="utf-8")

    assert contenu.index("## 2026-08-20") > contenu.index("## 2026-08-19")


def test_la_puce_vide_est_remplacee_et_non_doublee(service, chemin):
    service.capturer("une vraie ligne", now=LE_19)

    contenu = chemin.read_text(encoding="utf-8")

    assert "- une vraie ligne" in contenu
    assert "\n- \n" not in contenu

    aujourdhui = next(
        j for j in service.jours() if j.titre == "2026-08-19"
    )

    assert aujourdhui.lignes == ["une vraie ligne"]


def test_le_preambule_n_est_jamais_touche(service, chemin):
    avant = chemin.read_text(encoding="utf-8")

    service.capturer("une ligne", now=LE_19)

    apres = chemin.read_text(encoding="utf-8")

    entete = avant.split("## 2026-08-18")[0]

    assert apres.startswith(entete)


def test_deux_captures_se_suivent(service):
    service.capturer("premiere", now=LE_20)
    service.capturer("deuxieme", now=LE_20)

    assert service.jours()[0].lignes == ["premiere", "deuxieme"]


def test_le_texte_est_ramene_sur_une_ligne(service):
    """Un titre collé au milieu créerait une fausse journée."""
    service.capturer("une idee\n## Faux titre", now=LE_20)

    jours = service.jours()

    assert jours[0].lignes == ["une idee ## Faux titre"]
    assert len(jours) == 3


def test_une_puce_saisie_a_la_main_n_est_pas_doublee(service):
    service.capturer("- deja une puce", now=LE_20)

    assert service.jours()[0].lignes == ["deja une puce"]


def test_une_ligne_vide_est_refusee(service):
    with pytest.raises(journal.JournalError):
        service.capturer("   ")

    with pytest.raises(journal.JournalError):
        service.capturer("-")


def test_un_journal_en_lecture_seule_refuse_d_ecrire(temp_repository):
    lecture_seule = journal.JournalService(temp_repository)

    with pytest.raises(journal.JournalError):
        lecture_seule.capturer("une ligne")


def test_le_frontmatter_survit_a_la_capture(service, chemin, temp_vault):
    service.capturer("une ligne", now=LE_20)

    frontmatter = temp_vault.read_frontmatter(chemin)

    assert frontmatter["type"] == "journal"
    assert frontmatter["sujet"] == "Capture rapide"
