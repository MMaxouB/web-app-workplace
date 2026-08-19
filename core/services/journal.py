"""Journal de capture rapide (`07-Notes/Journal.md`, `type: journal`).

Un seul fichier, une section par jour, du plus ancien au plus
récent. Le geste décrit par les conventions tient en trois
secondes : ouvrir, `Ctrl + Fin`, écrire une ligne, fermer
(`03-Documentation/Notes et journal.md`).

Deux conséquences pour ce module.

**Le fichier est trouvé par son type, pas par son nom.** Les
conventions prévoient qu'il devienne `Journal 2026.md` le jour où il
sera trop gros, en précisant que rien ne dépend de son nom. Coder le
chemin en dur aurait démenti cette phrase à la première archive.

**On écrit à la suite, jamais en tête.** C'est l'inverse des
historiques de fiches, rangés du plus récent au plus ancien. Ici
l'ordre du fichier est chronologique, parce que `Ctrl + Fin` doit
amener le curseur là où l'on écrit.
"""

import datetime
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.obsidian.repository import ObsidianRepository
from core.obsidian.writer import VaultWriteError, VaultWriter, flatten


logger = logging.getLogger(__name__)


TYPE_JOURNAL = "journal"

# « ## 2026-08-18 » — exactement deux dièses : un seul referme la
# section du jour, trois en font un sous-titre à l'intérieur.
_TITRE_DE_JOUR = re.compile(r"^##(?!#)\s*(.+?)\s*$")

_TITRE_AUTRE = re.compile(r"^#(?!#)\s*(.+?)\s*$")

_PUCE = re.compile(r"^(\s*)[-*+]\s+(.*)$")


class JournalError(Exception):
    """Opération impossible, avec un message pour l'utilisateur."""


@dataclass(frozen=True)
class Jour:
    """Une journée du journal, telle qu'elle est écrite."""

    titre: str

    #: Date lue depuis le titre, ou None si le titre n'en est pas
    #: une. Un titre libre reste affiché : le Vault n'est pas
    #: propre, et une section mal titrée vaut mieux qu'une section
    #: perdue.
    date: datetime.date | None = None

    lignes: list[str] = field(default_factory=list)


def _date_de(titre: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(titre[:10])
    except ValueError:
        return None


def lire(corps: str) -> list[Jour]:
    """Découpe le corps du journal en journées, dans l'ordre du fichier.

    Tout ce qui précède la première date — le titre, la note
    d'usage, la règle horizontale — est ignoré : ce n'est pas du
    journal, c'est le mode d'emploi.

    Rien de ce qui suit une date n'est perdu, en revanche. Une puce
    fait une ligne ; une ligne indentée prolonge la précédente ; et
    tout autre texte devient une ligne à part entière plutôt que de
    disparaître.
    """
    jours: list[Jour] = []
    courant: Jour | None = None

    for ligne in corps.splitlines():
        titre_de_jour = _TITRE_DE_JOUR.match(ligne.strip())

        if titre_de_jour:
            titre = titre_de_jour.group(1)

            courant = Jour(titre=titre, date=_date_de(titre))

            jours.append(courant)
            continue

        if _TITRE_AUTRE.match(ligne.strip()):
            # Un titre de niveau 1 referme la journée en cours.
            courant = None
            continue

        if courant is None:
            continue

        puce = _PUCE.match(ligne)

        if puce:
            texte = puce.group(2).strip()

            # La puce vide déposée par le gabarit du jour est un
            # emplacement où écrire, pas une ligne du journal.
            if texte:
                courant.lignes.append(texte)

            continue

        if not ligne.strip():
            continue

        if ligne[:1].isspace() and courant.lignes:
            # Ligne indentée : elle prolonge la puce précédente.
            courant.lignes[-1] += "\n" + ligne.strip()
            continue

        courant.lignes.append(ligne.strip())

    return jours


def recents_d_abord(jours: list[Jour]) -> list[Jour]:
    """Du plus récent au plus ancien, pour l'affichage.

    Le fichier est chronologique parce qu'on y écrit à la fin ; un
    écran, lui, montre d'abord ce qui vient de se passer. Les
    journées sans date lisible restent en fin de liste, dans l'ordre
    du fichier.
    """
    dates = [jour for jour in jours if jour.date is not None]
    sans_date = [jour for jour in jours if jour.date is None]

    return (
        sorted(dates, key=lambda jour: jour.date, reverse=True)
        + sans_date
    )


class JournalService:
    """Lecture du journal et capture d'une ligne."""

    def __init__(
        self,
        repository: ObsidianRepository,
        writer: VaultWriter | None = None,
    ):
        self.repository = repository
        self.writer = writer

    # =====================================================
    # Localisation
    # =====================================================

    def chemin(self) -> Path:
        """Le fichier du journal, ou une erreur explicite.

        S'il en existe plusieurs — le jour où une année sera
        archivée — c'est le dernier modifié qui fait office de
        journal courant. Aucun fichier n'est créé ici : la web app
        n'invente pas de note que l'utilisateur n'a pas demandée.
        """
        trouves = [
            file_path
            for _, file_path in self.repository._collect(TYPE_JOURNAL)
        ]

        if not trouves:
            raise JournalError(
                "Aucune note « type: journal » dans le Vault. "
                "Le journal se crée dans Obsidian, à partir de "
                "99-Templates/jour-journal.md."
            )

        if len(trouves) == 1:
            return trouves[0]

        return max(trouves, key=lambda chemin: chemin.stat().st_mtime)

    # =====================================================
    # Lecture
    # =====================================================

    def jours(self) -> list[Jour]:
        """Journées du journal, de la plus récente à la plus ancienne."""
        corps = self.repository.vault.read_body(self.chemin())

        return recents_d_abord(lire(corps))

    # =====================================================
    # Écriture
    # =====================================================

    def capturer(
        self,
        texte: str,
        now: datetime.datetime | None = None,
    ) -> str:
        """Ajoute une ligne à la journée en cours.

        La ligne est ramenée sur une seule ligne, comme toute valeur
        qui vient d'un formulaire : le journal est fait de puces, et
        un titre Markdown collé au milieu créerait une fausse
        journée que les écritures suivantes viseraient.

        Si la journée n'existe pas encore, elle est ouverte à la fin
        du fichier — exactement ce que fait le gabarit
        `99-Templates/jour-journal.md`.
        """
        if self.writer is None:
            raise JournalError(
                "Ce journal a été ouvert en lecture seule."
            )

        propre = flatten(texte or "").strip()

        # « - idée » et « idée » veulent dire la même chose : on ne
        # va pas rendre une puce dans une puce. Le tiret n'est retiré
        # que s'il est suivi d'un espace ou seul sur la ligne : sinon
        # « -v ne marche pas » y perdrait son option.
        propre = re.sub(r"^[-*+](\s+|$)", "", propre).strip()

        if not propre:
            raise JournalError("La ligne est vide.")

        if now is None:
            now = datetime.datetime.now().astimezone()

        jour = now.date().isoformat()

        chemin = self.chemin()

        deja_la = any(
            existant.titre == jour
            for existant in lire(
                self.repository.vault.read_body(chemin)
            )
        )

        try:
            if deja_la:
                self.writer.append_bullet_to_section(
                    chemin,
                    f"## {jour}",
                    f"- {propre}",
                )
            else:
                self.writer.append_block(
                    chemin,
                    f"## {jour}\n\n- {propre}",
                )
        except VaultWriteError as error:
            raise JournalError(
                f"Ligne non ajoutée : {error}"
            ) from error

        logger.info("Ligne ajoutée au journal du %s.", jour)

        return propre
