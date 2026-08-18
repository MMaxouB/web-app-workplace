"""Socle commun aux services qui écrivent dans le Vault.

Les trois types de fiches (tâche, projet, collaborateur) partagent
la même mécanique : modifier le frontmatter, répercuter dans le
tableau du corps, consigner dans l'historique.

Leurs différences sont déclarées par des attributs de classe
plutôt que réécrites à chaque fois :

- `TABLE_LABELS`     quelle ligne de tableau correspond à quel champ
- `HISTORY_GROUPED`  puces groupées sous une date (projets,
                     collaborateurs) ou entrée horodatée par
                     modification (tâches, comme le template)

Règle constante : le frontmatter fait foi. Un tableau ou un
historique absent produit un avertissement, jamais un échec.
"""

import datetime
import logging
from pathlib import Path

from core.obsidian.repository import ObsidianRepository
from core.obsidian.writer import VaultWriteError, VaultWriter


logger = logging.getLogger(__name__)


HISTORY_SECTION = "## Historique"


class VaultNoteService:
    #: Correspondance champ du frontmatter -> libellé du tableau
    TABLE_LABELS: dict[str, str] = {}

    #: True  : puces regroupées sous « ### AAAA-MM-JJ »
    #: False : une entrée « ### JJ/MM/AAAA HH:mm » par modification
    HISTORY_GROUPED = False

    #: Nom du type de fiche, utilisé dans les messages
    KIND_LABEL = "fiche"

    def __init__(
        self,
        repository: ObsidianRepository,
        writer: VaultWriter,
    ):
        self.repository = repository
        self.writer = writer

    @property
    def vault_path(self) -> Path:
        return self.repository.vault.path

    # =====================================================
    # À redéfinir si la fiche affiche des libellés lisibles
    # =====================================================

    def display_value(self, key: str, value: str) -> str:
        """Valeur telle qu'elle doit apparaître dans le tableau."""
        return value

    # =====================================================
    # Écritures secondaires
    # =====================================================

    def sync_table(
        self,
        path: Path,
        key: str,
        value: str,
    ) -> str | None:
        """Répercute un champ dans le tableau du corps de la fiche."""
        label = self.TABLE_LABELS.get(key)

        if label is None:
            return None

        try:
            if self.writer.set_table_field(
                path,
                label,
                self.display_value(key, value),
            ):
                return None
        except VaultWriteError as error:
            logger.warning(
                "Tableau non mis à jour (%s) : %s",
                path.name,
                error,
            )

            return f"Tableau non mis à jour : {error}"

        return (
            f"La {self.KIND_LABEL} n'a pas de ligne « {label} » "
            "dans son tableau : seul le frontmatter a été modifié."
        )

    def add_history(
        self,
        path: Path,
        message: str,
        now: datetime.datetime | None = None,
    ) -> str | None:
        """Consigne une modification dans « ## Historique »."""
        if now is None:
            now = datetime.datetime.now().astimezone()

        try:
            if self.HISTORY_GROUPED:
                self.writer.add_bullet_under_heading(
                    path,
                    HISTORY_SECTION,
                    f"### {now.date().isoformat()}",
                    f"- {message}",
                )
            else:
                self.writer.prepend_to_section(
                    path,
                    HISTORY_SECTION,
                    f"### {now.strftime('%d/%m/%Y %H:%M')}\n\n"
                    f"- {message}",
                )
        except VaultWriteError as error:
            logger.warning(
                "Historique non mis à jour (%s) : %s",
                path.name,
                error,
            )

            return (
                f"La {self.KIND_LABEL} n'a pas de section "
                "« Historique » : la modification n'y a pas été "
                "consignée."
            )

        return None

    def record(
        self,
        warnings: list[str],
        path: Path,
        key: str,
        value: str,
        message: str,
    ) -> None:
        """Tableau puis historique, en collectant les avertissements."""
        for warning in (
            self.sync_table(path, key, value),
            self.add_history(path, message),
        ):
            if warning:
                warnings.append(warning)

    # =====================================================
    # Aide à la résolution
    # =====================================================

    @staticmethod
    def ambiguity_message(
        name: str,
        candidates: list[str],
        plural_label: str,
    ) -> str:
        noms = "\n".join(f"• {candidate}" for candidate in candidates)

        return (
            f"Plusieurs {plural_label} correspondent à « {name} » :\n"
            f"{noms}\n\nPrécise ta recherche."
        )
