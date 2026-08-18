"""Fil d'activité du Vault (§29).

Le cahier des charges propose de stocker l'historique « dans une zone
système du Vault si nécessaire ». Ce n'est pas nécessaire, et ce
serait contraire au §33 : chaque note tient déjà son propre
`## Historique`, écrit à chaque modification. Ce module les relit et
les fusionne en un seul fil, du plus récent au plus ancien.

Aucune donnée nouvelle n'est créée. Le Vault reste la seule source,
et un historique effacé à la main dans Obsidian disparaît du fil —
c'est le comportement attendu d'une vue, pas d'un journal parallèle.

Deux formats de sous-titre coexistent dans le Vault, selon ce
qu'écrivaient les services :

    ### 17/08/2026 16:15     tâches — une entrée par modification
    ### 2026-08-17           projets, collaborateurs — puces groupées

Les deux sont reconnus. Une date illisible n'est pas une erreur : le
groupe est simplement ignoré plutôt que de faire échouer la lecture
de tout le Vault.
"""

import datetime
import re
from dataclasses import dataclass
from pathlib import Path


SECTION = "## Historique"

# « ### 17/08/2026 16:15 » ou « ### 17/08/2026 »
_FR = re.compile(
    r"^(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$"
)

# « ### 2026-08-17 » ou « ### 2026-08-17 16:15 »
_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{1,2}):(\d{2}))?$"
)


# Les entrées écrites par l'application ont une forme reconnaissable.
# Tout le reste a été rédigé à la main : ce sont des comptes rendus,
# pas des changements, et ils n'ont pas leur place dans le même
# filtre — un seul d'entre eux peut faire dix lignes et enterrer
# vingt changements réels.
_GENRES = (
    ("creation", re.compile(r"^(tâche|fiche|projet)\s+cré", re.I)),
    ("statut", re.compile(r"^statut\s+pass", re.I)),
    ("priorite", re.compile(r"^priorité\s+pass", re.I)),
    ("echeance", re.compile(r"^(délai\s*:|échéance\s+déplacée)", re.I)),
    ("champ", re.compile(r"^champ\s+`", re.I)),
)


def genre_de(texte: str) -> str:
    """Classe une entrée : quel genre de changement décrit-elle ?"""
    for genre, motif in _GENRES:
        if motif.search(texte.strip()):
            return genre

    return "note"


@dataclass(frozen=True)
class Entree:
    """Une ligne du fil d'activité."""

    quand: datetime.datetime
    #: True quand le sous-titre ne portait qu'une date, sans heure.
    jour_seul: bool
    texte: str
    note: str
    type_note: str
    chemin: Path
    genre: str = "note"

    @property
    def date(self) -> datetime.date:
        return self.quand.date()

    @property
    def automatique(self) -> bool:
        """Écrite par l'application, par opposition à rédigée à la main."""
        return self.genre != "note"


def parse_titre_date(titre: str) -> tuple[datetime.datetime, bool] | None:
    """Lit un sous-titre daté. None si ce n'en est pas un."""
    texte = titre.strip().lstrip("#").strip()

    correspondance = _FR.match(texte)

    if correspondance:
        jour, mois, annee, heure, minute = correspondance.groups()
    else:
        correspondance = _ISO.match(texte)

        if not correspondance:
            return None

        annee, mois, jour, heure, minute = correspondance.groups()

    try:
        moment = datetime.datetime(
            int(annee),
            int(mois),
            int(jour),
            int(heure) if heure else 0,
            int(minute) if minute else 0,
        )
    except ValueError:
        # 31/02/2026 et autres dates impossibles.
        return None

    return moment, heure is None


def extraire_section(corps: str) -> list[str]:
    """Lignes de la section « ## Historique », sans son titre."""
    lignes = corps.splitlines()

    debut = None

    for index, ligne in enumerate(lignes):
        if ligne.strip().casefold() == SECTION.casefold():
            debut = index + 1
            break

    if debut is None:
        return []

    for index in range(debut, len(lignes)):
        depouillee = lignes[index].strip()

        # Un titre de même niveau ferme la section. Les « ### »
        # datés lui appartiennent.
        if depouillee.startswith("## ") or depouillee == "##":
            return lignes[debut:index]

    return lignes[debut:]


def lire_entrees(
    corps: str,
    *,
    note: str,
    type_note: str,
    chemin: Path,
) -> list[Entree]:
    """Toutes les entrées datées du « ## Historique » d'une note."""
    entrees: list[Entree] = []

    moment: datetime.datetime | None = None
    jour_seul = False

    for ligne in extraire_section(corps):
        depouillee = ligne.strip()

        if depouillee.startswith("#"):
            lu = parse_titre_date(depouillee)

            if lu is None:
                # Un sous-titre non daté ferme le groupe courant :
                # les puces qui suivent ne sont datées de rien.
                moment = None
            else:
                moment, jour_seul = lu

            continue

        if moment is None:
            continue

        if not depouillee.startswith("- "):
            # Continuation d'une puce, ou sous-liste : rattachée à
            # l'entrée précédente, on ne la duplique pas.
            continue

        texte = depouillee[2:].strip()

        if not texte:
            continue

        entrees.append(
            Entree(
                quand=moment,
                jour_seul=jour_seul,
                texte=texte,
                note=note,
                type_note=type_note,
                chemin=chemin,
                genre=genre_de(texte),
            )
        )

    return entrees


def fusionner(entrees: list[Entree]) -> list[Entree]:
    """Trie du plus récent au plus ancien.

    À égalité de date, les entrées datées à la minute passent avant
    celles datées au jour : elles sont plus précises, donc plus
    informatives.
    """
    return sorted(
        entrees,
        key=lambda e: (e.quand, not e.jour_seul),
        reverse=True,
    )


def grouper_par_jour(
    entrees: list[Entree],
) -> list[tuple[datetime.date, list[Entree]]]:
    """Regroupe le fil par journée, dans l'ordre du fil."""
    jours: dict[datetime.date, list[Entree]] = {}

    for entree in entrees:
        jours.setdefault(entree.date, []).append(entree)

    return sorted(jours.items(), key=lambda paire: paire[0], reverse=True)
