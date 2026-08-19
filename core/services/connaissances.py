"""Lecture de la base de connaissances (`06-Connaissances/`).

Ce module ne fait que lire. Les connaissances se créent dans
Obsidian, par le template `99-Templates/template-connaissance.md`
qui pose le frontmatter, range le fichier et propose le squelette de
la catégorie choisie — la web app n'a rien de mieux à offrir pour
ça, et deux chemins de création finiraient par diverger.

Ce qu'elle apporte, c'est la navigation : un dossier dit un sujet,
et il faut pouvoir descendre `domaine → sujet`, filtrer par sorte de
note et par maturité, et traverser tout ça par les tags.

Deux règles gouvernent le reste, et viennent des conventions
(`03-Documentation/Base de connaissances.md`) :

- **le dossier dit le sujet, jamais l'avancement** ; une note ne
  déménage donc jamais, et c'est `maturite:` qui évolue ;
- `domaine` dit **de quoi ça parle**, `categorie` dit **quelle sorte
  de note c'est** — les deux axes sont indépendants.
"""

from dataclasses import dataclass, field
from pathlib import Path

from core.obsidian.models import Knowledge
from core.utils.text import matches_exactly, normalize


#: Dossier racine de la base, tel qu'il est nommé dans le Vault.
RACINE = "06-Connaissances"

#: Sortes de notes, dans l'ordre du template Templater.
CATEGORIES = (
    "concept",
    "technique",
    "outil",
    "langage",
    "architecture",
    "guide",
    "reference",
    "writeup",
)

#: Maturités, de la plus brute à la plus sûre. L'ordre compte : il
#: sert à trier « ce qui reste à reprendre ».
MATURITES = ("graine", "brouillon", "stable")

#: Libellé des regroupements sans valeur. Une note dont le domaine
#: n'est ni déclaré ni déductible du dossier existe quand même : elle
#: doit rester visible, pas disparaître d'un filtre.
SANS_DOMAINE = "Sans domaine"

SANS_SUJET = ""


# =====================================================
# Où la note est rangée
# =====================================================


def segments(note: Knowledge, vault_path: Path) -> tuple[str, ...]:
    """Dossiers traversés sous `06-Connaissances/`, sans le fichier.

    Renvoie un n-uplet vide pour une note posée ailleurs : le Vault
    n'est pas propre, et une connaissance égarée hors de la base ne
    doit pas faire échouer la navigation.
    """
    try:
        relatif = note.path.resolve().relative_to(vault_path)
    except ValueError:
        return ()

    parties = relatif.parts

    if len(parties) < 2 or parties[0] != RACINE:
        return ()

    return parties[1:-1]


def domaine_de(note: Knowledge, vault_path: Path) -> str:
    """Domaine de la note : celui qu'elle déclare, sinon son dossier.

    Le champ fait foi — c'est lui que lisent les requêtes Dataview.
    Le dossier ne sert que de secours, pour qu'une note au
    frontmatter incomplet reste navigable au lieu de tomber dans un
    fourre-tout.
    """
    if note.domaine:
        return note.domaine

    ranges = segments(note, vault_path)

    return ranges[0] if ranges else SANS_DOMAINE


def sujet_de(note: Knowledge, vault_path: Path) -> str:
    """Sous-dossier de la note, ou chaîne vide s'il n'y en a pas.

    `Concepts/` et `References/` n'ont pas de sous-dossier : leurs
    notes n'ont pas de sujet, et ce n'est pas un manque.
    """
    if note.sujet:
        return note.sujet

    ranges = segments(note, vault_path)

    return ranges[1] if len(ranges) > 1 else SANS_SUJET


def dossier_coherent(note: Knowledge, vault_path: Path) -> bool:
    """Le `domaine:` déclaré se retrouve-t-il dans le chemin ?

    Reprend le contrôle Dataview des conventions. Une note dont le
    domaine ne correspond pas à son dossier n'est pas cassée, mais
    elle est introuvable là où on la cherchera.
    """
    if not note.domaine:
        return False

    return any(
        matches_exactly(partie, note.domaine)
        for partie in segments(note, vault_path)
    )


# =====================================================
# Arborescence
# =====================================================


@dataclass(frozen=True)
class Rameau:
    """Un sujet, et le nombre de notes qu'il contient."""

    sujet: str
    total: int = 0


@dataclass(frozen=True)
class Branche:
    """Un domaine, ses sujets et son total."""

    domaine: str
    total: int = 0
    sujets: list[Rameau] = field(default_factory=list)


def arborescence(
    notes: list[Knowledge],
    vault_path: Path,
) -> list[Branche]:
    """Domaines et sujets présents, avec leurs compteurs.

    Construite depuis les notes elles-mêmes plutôt que depuis les
    dossiers du disque : un dossier vide n'a rien à proposer, et
    l'arborescence complète existe déjà dans les conventions.
    """
    par_domaine: dict[str, dict[str, int]] = {}

    for note in notes:
        domaine = domaine_de(note, vault_path)
        sujet = sujet_de(note, vault_path)

        par_domaine.setdefault(domaine, {})
        par_domaine[domaine][sujet] = (
            par_domaine[domaine].get(sujet, 0) + 1
        )

    branches = []

    for domaine, sujets in par_domaine.items():
        rameaux = [
            Rameau(sujet=sujet, total=total)
            for sujet, total in sorted(
                sujets.items(),
                key=lambda couple: (
                    couple[0] == SANS_SUJET,
                    couple[0].casefold(),
                ),
            )
        ]

        branches.append(
            Branche(
                domaine=domaine,
                total=sum(sujets.values()),
                sujets=rameaux,
            )
        )

    # « Sans domaine » ferme la marche : c'est un défaut de
    # rangement, pas une rubrique.
    return sorted(
        branches,
        key=lambda branche: (
            branche.domaine == SANS_DOMAINE,
            branche.domaine.casefold(),
        ),
    )


# =====================================================
# Filtres et tris
# =====================================================


def filtrer(
    notes: list[Knowledge],
    vault_path: Path,
    *,
    domaine: str | None = None,
    sujet: str | None = None,
    categorie: str | None = None,
    maturite: str | None = None,
    tag: str | None = None,
) -> list[Knowledge]:
    """Applique les filtres demandés, en ignorant ceux qui sont vides.

    Les comparaisons sont tolérantes — sans accents, sans casse —
    comme partout ailleurs : un tag saisi « Élévation » doit
    retrouver `elevation`, sinon le filtre ne sert à rien.
    """
    retenues = notes

    if domaine:
        retenues = [
            note
            for note in retenues
            if matches_exactly(domaine_de(note, vault_path), domaine)
        ]

    if sujet:
        retenues = [
            note
            for note in retenues
            if matches_exactly(sujet_de(note, vault_path), sujet)
        ]

    if categorie:
        retenues = [
            note
            for note in retenues
            if matches_exactly(note.categorie, categorie)
        ]

    if maturite:
        retenues = [
            note
            for note in retenues
            if matches_exactly(note.maturite, maturite)
        ]

    if tag:
        vise = normalize(tag)

        retenues = [
            note
            for note in retenues
            if any(normalize(porte) == vise for porte in note.tags)
        ]

    return retenues


def trier(notes: list[Knowledge], vault_path: Path) -> list[Knowledge]:
    """Par domaine, puis sujet, puis nom — l'ordre des dossiers."""
    return sorted(
        notes,
        key=lambda note: (
            domaine_de(note, vault_path).casefold(),
            sujet_de(note, vault_path).casefold(),
            note.name.casefold(),
        ),
    )


def compter_tags(notes: list[Knowledge]) -> list[tuple[str, int]]:
    """Tags employés, du plus fréquent au moins fréquent.

    Les variantes d'écriture sont regroupées — `#XSS` et `#xss` sont
    le même tag — et c'est la première orthographe rencontrée qui
    représente le groupe, faute d'une raison d'en préférer une autre.
    """
    compte: dict[str, int] = {}
    libelle: dict[str, str] = {}

    for note in notes:
        for tag in note.tags:
            cle = normalize(tag)

            if not cle:
                continue

            compte[cle] = compte.get(cle, 0) + 1
            libelle.setdefault(cle, tag)

    return [
        (libelle[cle], total)
        for cle, total in sorted(
            compte.items(),
            key=lambda couple: (-couple[1], couple[0]),
        )
    ]


def compter(
    notes: list[Knowledge],
    valeurs: tuple[str, ...],
    champ: str,
) -> list[tuple[str, int]]:
    """Compte les notes par valeur d'un champ, valeurs connues d'abord.

    Sert aux filtres de l'interface : proposer « guide » alors
    qu'aucun guide n'existe encore n'aide personne, et masquer une
    valeur inattendue la rendrait introuvable.
    """
    compte: dict[str, int] = {}

    for note in notes:
        brut = (getattr(note, champ, None) or "").strip()

        cle = brut.casefold() if brut else ""

        if cle:
            compte[cle] = compte.get(cle, 0) + 1

    connues = [
        (valeur, compte[valeur])
        for valeur in valeurs
        if compte.get(valeur)
    ]

    autres = sorted(
        (cle, total)
        for cle, total in compte.items()
        if cle not in valeurs
    )

    return connues + autres
