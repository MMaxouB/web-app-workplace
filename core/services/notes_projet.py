"""Notes de projet (`07-Notes/`, `type: note`).

À ne pas confondre avec `core/services/notes.py`, qui ajoute un
texte libre sous le « ## Notes » d'une fiche existante. Ici, la note
**est** le fichier : un sujet, un projet, et une liste de points
qu'on coche au fil de l'eau.

Une note n'a aucune criticité — ni priorité, ni statut, ni échéance
(`03-Documentation/Notes et journal.md`). Il n'y a donc rien à
décider en l'écrivant et rien à tenir à jour ensuite : son
avancement se lit dans ses cases cochées, et nulle part ailleurs.
C'est aussi pourquoi elle ne change jamais de dossier, contrairement
aux tâches.

La seule écriture proposée est donc la bascule d'une case.
"""

import datetime
import logging

from core.obsidian.models import Note, Project
from core.obsidian.repository import ObsidianRepository, belongs_to
from core.obsidian.writer import VaultWriteError, VaultWriter
from core.services.analytics import Progression
from core.utils.markdown import Case, lire_cases


logger = logging.getLogger(__name__)


class NoteProjetError(Exception):
    """Opération impossible, avec un message pour l'utilisateur."""


def points(corps: str) -> list[Case]:
    """Cases à cocher d'une note, dans l'ordre du fichier."""
    return lire_cases(corps)


def progression(cases: list[Case]) -> Progression:
    """Avancement d'une note : la part de ses cases cochées.

    Renvoie la même `Progression` que les tâches d'un projet, pour
    que l'interface affiche les deux avec la même barre. Une note
    sans case rend 0 sur 0, ce qui est exact : elle n'a rien à
    avancer, elle n'est pas en retard.
    """
    return Progression(
        termine=sum(1 for case in cases if case.cochee),
        total=len(cases),
    )


def orphelines(
    projets: list[Project],
    notes: list[Note],
) -> list[Note]:
    """Notes qui ne retombent sur aucun projet du Vault.

    Les conventions confient explicitement ce contrôle à la web app :
    Dataview ne sait pas confronter deux ensembles de notes dans une
    même requête, « la comparaison tolérante, sans accents ni casse,
    reste le travail de la web app ».

    Deux cas s'y mélangent, et c'est voulu : la note sans projet, qui
    est légitime, et la note dont le `project:` comporte une faute de
    frappe, qui ne l'est pas. Les distinguer demande de regarder —
    c'est le rôle de l'écran, pas du service.
    """
    return [
        note
        for note in notes
        if not any(belongs_to(note, projet) for projet in projets)
    ]


class NoteProjetService:
    """Écritures sur une note de projet : cocher, décocher."""

    def __init__(
        self,
        repository: ObsidianRepository,
        writer: VaultWriter,
    ):
        self.repository = repository
        self.writer = writer

    def basculer(
        self,
        note: Note,
        index: int,
        cochee: bool,
        *,
        texte_attendu: str | None = None,
        today: datetime.date | None = None,
    ) -> tuple[str, list[str]]:
        """Coche ou décoche le point de rang `index`.

        Renvoie le libellé du point et les avertissements éventuels.
        Comme partout : le contenu de la note fait foi, et ce qui est
        secondaire — ici la date de dernière modification — ne peut
        jamais faire échouer l'opération.
        """
        try:
            texte, modifiee = self.writer.set_checkbox(
                note.path,
                index,
                cochee,
                texte_attendu=texte_attendu,
            )
        except VaultWriteError as error:
            raise NoteProjetError(str(error)) from error

        avertissements: list[str] = []

        # Recocher une case déjà cochée n'est pas une modification :
        # ni le corps ni la date ne bougent.
        if not modifiee:
            return texte, avertissements

        self._dater(note, avertissements, today)

        logger.info(
            "Point %d de « %s » : %s",
            index + 1,
            note.name,
            "coché" if cochee else "décoché",
        )

        return texte, avertissements

    def _dater(
        self,
        note: Note,
        avertissements: list[str],
        today: datetime.date | None = None,
    ) -> None:
        """Met `mis_a_jour` au jour même, si ce n'est pas déjà le cas.

        Les conventions présentent ce champ comme la date de dernière
        modification de la note, et une requête Dataview trie dessus.
        Cocher un point est bien une modification.

        L'écriture n'a lieu que si la date change : cocher trois
        points le même jour ne réécrit le frontmatter qu'une fois, et
        ne réveille le surveillant d'Obsidian qu'une fois de plus.

        La date est relue dans le fichier plutôt que prise dans le
        modèle reçu : l'appelant travaille souvent sur une note lue
        avant la première case, et se fier à elle réécrirait la même
        valeur à chaque clic.
        """
        if today is None:
            today = datetime.date.today()

        jour = today.isoformat()

        donnees = self.repository.vault.safe_read_frontmatter(note.path)

        if donnees and str(donnees.get("mis_a_jour")) == jour:
            return

        try:
            self.writer.set_frontmatter_field(
                note.path,
                "mis_a_jour",
                jour,
            )
        except VaultWriteError as error:
            logger.warning(
                "Date de mise à jour non écrite (%s) : %s",
                note.path.name,
                error,
            )

            avertissements.append(
                "Le champ « mis_a_jour » n'a pas pu être mis à "
                f"jour : {error}"
            )
