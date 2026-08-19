"""Lecture des cases à cocher d'une note.

Les notes de `07-Notes/` n'ont ni statut ni priorité : leur
avancement se lit dans leurs cases cochées, et nulle part ailleurs
(`03-Documentation/Notes et journal.md`). Il faut donc savoir les
retrouver — pour les afficher, et pour en modifier une sans toucher
au reste du fichier.

Une case est désignée par son **rang dans la note**, pas par son
numéro de ligne. Le rang est ce que l'interface voit et ce qui
survit à l'ajout d'un paragraphe au-dessus ; le numéro de ligne,
lui, ne survit à rien. Le libellé sert de garde-fou au moment
d'écrire : si la ligne visée ne dit plus la même chose, on refuse
plutôt que de cocher la mauvaise case.
"""

import re
from dataclasses import dataclass


# `- [ ] texte`, `* [x] texte`, avec l'indentation d'une sous-liste.
MOTIF_CASE = re.compile(
    r"^(?P<avant>\s*[-*+]\s+\[)(?P<etat>[ xX])(?P<apres>\])(?P<texte>.*)$"
)


@dataclass(frozen=True)
class Case:
    """Une case à cocher, telle qu'elle est écrite dans la note."""

    #: Rang de la case dans la note, à partir de 0.
    index: int

    #: Numéro de la ligne dans le fichier, à partir de 0.
    ligne: int

    cochee: bool

    texte: str

    #: Profondeur d'indentation, en espaces. Une sous-case reste
    #: rattachée visuellement à celle qui la précède.
    niveau: int = 0


def lire_cases(contenu: str, depart: int = 0) -> list[Case]:
    """Toutes les cases d'un texte, dans l'ordre du fichier.

    `depart` permet de sauter le frontmatter quand on travaille sur
    le fichier entier plutôt que sur son corps : les rangs restent
    alors identiques des deux côtés.
    """
    cases = []

    for numero, ligne in enumerate(contenu.splitlines()):
        if numero < depart:
            continue

        trouve = MOTIF_CASE.match(ligne)

        if trouve is None:
            continue

        avant = trouve.group("avant")

        cases.append(
            Case(
                index=len(cases),
                ligne=numero,
                cochee=trouve.group("etat").lower() == "x",
                texte=trouve.group("texte").strip(),
                niveau=len(avant) - len(avant.lstrip()),
            )
        )

    return cases


def ecrire_case(ligne: str, cochee: bool) -> str:
    """Renvoie la même ligne, case cochée ou décochée.

    Tout le reste est conservé : l'indentation, le tiret utilisé, le
    texte, l'espacement et la fin de ligne. Un seul caractère change.
    """
    corps = ligne.rstrip("\r\n")
    fin = ligne[len(corps) :]

    trouve = MOTIF_CASE.match(corps)

    if trouve is None:
        raise ValueError("Cette ligne ne porte pas de case à cocher.")

    return (
        trouve.group("avant")
        + ("x" if cochee else " ")
        + trouve.group("apres")
        + trouve.group("texte")
        + fin
    )


# =====================================================
# Liens internes
# =====================================================

MOTIF_LIEN = re.compile(r"\[\[([^\]]+)\]\]")


def lire_liens(contenu: str) -> list[str]:
    """Cibles des liens `[[...]]`, sans alias ni ancre, sans doublon.

    Obsidian écrit `[[Note]]`, `[[Note|autre nom]]` et
    `[[Note#Section]]` : seul le nom du fichier nous intéresse, le
    reste est de la présentation.

    L'ordre d'apparition est conservé — c'est celui du texte, donc
    celui que l'auteur a choisi.
    """
    cibles = []

    for brut in MOTIF_LIEN.findall(contenu):
        cible = brut.split("|")[0].split("#")[0].strip()

        if cible and cible not in cibles:
            cibles.append(cible)

    return cibles
