"""Logique métier des projets.

Le format produit suit 99-Templates/template-projet.md, avec deux
adaptations tirées des fiches réelles du Vault :

- le tableau « Informations » affiche des libellés lisibles
  (« Actif », « High ») et non les valeurs brutes du frontmatter ;
- la section « Historique » groupe les puces sous une date ISO,
  au lieu de créer une entrée par modification.
"""

import datetime
import logging
from dataclasses import dataclass, field

from core.obsidian.models import Project
from core.obsidian.repository import ObsidianRepository
from core.obsidian.writer import VaultWriteError, VaultWriter
from core.services.base import VaultNoteService
from core.services.tasks import TaskError, sanitize_filename


logger = logging.getLogger(__name__)


def libelle_precedent(valeur) -> str:
    """Valeur précédente, telle qu'elle doit apparaître dans l'historique.

    `getattr(..., None)` rend None pour un champ vide, et le laisser
    tel quel écrirait « Champ `company` : `None` → … » dans une note
    que l'utilisateur relit.
    """
    return str(valeur) if valeur not in (None, "") else "vide"


STATUS_FOLDERS = {
    "active": "02-Projects/Actifs",
    "waiting": "02-Projects/En attente",
    "completed": "02-Projects/Terminés",
    "archived": "02-Projects/Archives",
}

VALID_STATUSES = tuple(STATUS_FOLDERS)

VALID_PRIORITIES = ("critical", "high", "medium", "low")

# Libellés utilisés dans le tableau des fiches projet.
STATUS_DISPLAY = {
    "active": "Actif",
    "waiting": "En attente",
    "completed": "Terminé",
    "archived": "Archivé",
}

FIELD_TABLE_LABELS = {
    "status": "Statut",
    "priority": "Priorité",
    "category": "Catégorie",
    "created": "Création",
    "deadline": "Deadline",
}

HISTORY_SECTION = "## Historique"

EDITABLE_FIELDS = (
    "category",
    "deadline",
    "repository",
    "name",
)


class ProjectError(Exception):
    """Opération impossible, avec un message pour l'utilisateur."""


@dataclass
class ProjectUpdate:
    project: Project
    warnings: list[str] = field(default_factory=list)


def display_value(key: str, value: str) -> str:
    """Rend une valeur lisible pour le tableau de la fiche."""
    if key == "status":
        return STATUS_DISPLAY.get(value, value)

    if key in ("priority", "category"):
        return value.capitalize()

    return value


def build_project_content(
    *,
    name: str,
    status: str,
    category: str,
    priority: str,
    deadline: str,
    repository: str,
    now: datetime.datetime,
) -> str:
    created = now.date().isoformat()

    return f"""---
type: project
status: {status}
name: {name}
category: {category}
priority: {priority}
created: {created}
deadline: {deadline}
repository: {repository}
---

# {name}

## Informations

| Champ     | Information |
| --------- | ----------- |
| Statut    | {display_value("status", status)} |
| Priorité  | {display_value("priority", priority)} |
| Catégorie | {display_value("category", category)} |
| Création  | {created} |
| Deadline  | {deadline or "—"} |

## Description

...

## Objectif

...

## Collaborateurs

-

## Responsabilités

### Nom

-

## Technologies

-

## Repository

{repository or "-"}

## Roadmap

### Phase 1

- [ ]

### Phase 2

- [ ]

### Phase 3

- [ ]

## Décisions importantes

### {created}

**Décision :**

...

**Raison :**

...

## Problèmes / Risques

-

## Notes

...

## Historique

### {created}
- Projet créé depuis la web app.
"""


class ProjectService(VaultNoteService):
    TABLE_LABELS = FIELD_TABLE_LABELS
    HISTORY_GROUPED = True
    KIND_LABEL = "fiche projet"

    def display_value(self, key: str, value: str) -> str:
        return display_value(key, value)

    # =====================================================
    # Résolution
    # =====================================================

    def resolve_project(self, name: str | Project) -> Project:
        # Un projet déjà résolu est accepté tel quel : l'API web
        # désigne les notes par leur chemin, sans ambiguïté.
        if isinstance(name, Project):
            return name

        project = self.repository.find_project(name)

        if project is not None:
            return project

        candidates = self.repository.find_matching_projects(name)

        if not candidates:
            raise ProjectError(
                f"Aucun projet ne correspond à « {name} »."
            )

        noms = "\n".join(
            f"• {candidate.name}" for candidate in candidates
        )

        raise ProjectError(
            f"Plusieurs projets correspondent à « {name} » :\n"
            f"{noms}\n\nPrécise ta recherche."
        )

    # =====================================================
    # Modifications
    # =====================================================

    def change_status(self, name: str, status: str) -> ProjectUpdate:
        status = status.strip().casefold()

        if status not in VALID_STATUSES:
            raise ProjectError(
                f"Statut invalide : « {status} ». "
                f"Valeurs acceptées : {', '.join(VALID_STATUSES)}."
            )

        project = self.resolve_project(name)

        if project.status == status:
            raise ProjectError(
                f"« {project.name} » est déjà au statut "
                f"« {status} »."
            )

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                project.path,
                "status",
                status,
            )

            self.record(
                warnings,
                project.path,
                "status",
                status,
                f"Statut passé de `{project.status}` à "
                f"`{status}` (depuis la web app).",
            )

            destination = self.vault_path / STATUS_FOLDERS[status]

            new_path = self.writer.move_note(
                project.path,
                destination,
            )
        except VaultWriteError as error:
            raise ProjectError(str(error)) from error

        logger.info(
            "Statut du projet « %s » : %s -> %s",
            project.name,
            project.status,
            status,
        )

        return ProjectUpdate(
            self.repository.vault.read_project(new_path),
            warnings,
        )

    def change_priority(
        self,
        name: str,
        priority: str,
    ) -> ProjectUpdate:
        priority = priority.strip().casefold()

        if priority not in VALID_PRIORITIES:
            raise ProjectError(
                f"Priorité invalide : « {priority} ». "
                f"Valeurs acceptées : {', '.join(VALID_PRIORITIES)}."
            )

        project = self.resolve_project(name)

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                project.path,
                "priority",
                priority,
            )

            self.record(
                warnings,
                project.path,
                "priority",
                priority,
                f"Priorité passée de `{project.priority}` à "
                f"`{priority}` (depuis la web app).",
            )
        except VaultWriteError as error:
            raise ProjectError(str(error)) from error

        return ProjectUpdate(
            self.repository.vault.read_project(project.path),
            warnings,
        )

    def set_field(
        self,
        name: str,
        key: str,
        value: str,
    ) -> ProjectUpdate:
        key = key.strip().casefold()

        if key not in EDITABLE_FIELDS:
            raise ProjectError(
                f"Champ non modifiable : « {key} ». "
                f"Champs autorisés : {', '.join(EDITABLE_FIELDS)}."
            )

        project = self.resolve_project(name)

        previous = getattr(project, key, None)

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                project.path,
                key,
                value,
            )

            self.record(
                warnings,
                project.path,
                key,
                value,
                f"Champ `{key}` : `{libelle_precedent(previous)}` → `{value}` "
                "(depuis la web app).",
            )
        except VaultWriteError as error:
            raise ProjectError(str(error)) from error

        return ProjectUpdate(
            self.repository.vault.read_project(project.path),
            warnings,
        )

    # =====================================================
    # Lien avec le salon Discord
    # =====================================================

    def link_panel(
        self,
        name: str,
        channel_id: int,
        message_id: int,
    ) -> ProjectUpdate:
        """Rattache un projet à son salon et à son panneau épinglé.

        Volontairement hors de `set_field` : ces deux champs sont
        écrits par le bot, jamais saisis à la main, et ne doivent
        donc pas apparaître dans `EDITABLE_FIELDS`.

        L'historique ne retient que le rattachement au salon. Un
        panneau reposté change d'identifiant de message sans que
        rien de significatif ne se soit produit : le consigner
        remplirait la fiche de bruit.
        """
        project = self.resolve_project(name)

        nouveau_salon = project.discord_channel_id != str(channel_id)

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                project.path,
                "discord_channel_id",
                str(channel_id),
            )

            self.writer.set_frontmatter_field(
                project.path,
                "discord_panel_message",
                str(message_id),
            )

            if nouveau_salon:
                warning = self.add_history(
                    project.path,
                    "Panneau installé dans le salon Discord "
                    f"`{channel_id}`.",
                )

                if warning:
                    warnings.append(warning)
        except VaultWriteError as error:
            raise ProjectError(str(error)) from error

        logger.info(
            "Panneau de « %s » : salon %s, message %s",
            project.name,
            channel_id,
            message_id,
        )

        return ProjectUpdate(
            self.repository.vault.read_project(project.path),
            warnings,
        )

    def unlink_panel(self, name: str) -> ProjectUpdate:
        """Oublie le panneau, sans toucher au rattachement au salon.

        Sert quand le message a disparu : le projet reste lié à
        son salon, seul le panneau est à reposer.
        """
        project = self.resolve_project(name)

        try:
            self.writer.set_frontmatter_field(
                project.path,
                "discord_panel_message",
                "",
            )
        except VaultWriteError as error:
            raise ProjectError(str(error)) from error

        return ProjectUpdate(
            self.repository.vault.read_project(project.path),
            [],
        )

    # =====================================================
    # Création
    # =====================================================

    def create_project(
        self,
        *,
        name: str,
        category: str = "",
        priority: str = "medium",
        deadline: str = "",
        repository: str = "",
        status: str = "active",
        now: datetime.datetime | None = None,
    ) -> Project:
        status = status.strip().casefold()
        priority = priority.strip().casefold()

        if status not in VALID_STATUSES:
            raise ProjectError(
                f"Statut invalide : « {status} »."
            )

        if priority not in VALID_PRIORITIES:
            raise ProjectError(
                f"Priorité invalide : « {priority} ». "
                f"Valeurs acceptées : {', '.join(VALID_PRIORITIES)}."
            )

        try:
            filename = sanitize_filename(name)
        except TaskError as error:
            raise ProjectError(str(error)) from error

        if self.repository.find_project(filename) is not None:
            raise ProjectError(
                f"Un projet « {filename} » existe déjà."
            )

        if now is None:
            now = datetime.datetime.now().astimezone()

        content = build_project_content(
            name=filename,
            status=status,
            category=category,
            priority=priority,
            deadline=deadline,
            repository=repository,
            now=now,
        )

        destination = (
            self.vault_path
            / STATUS_FOLDERS[status]
            / f"{filename}.md"
        )

        try:
            created = self.writer.create_note(destination, content)
        except VaultWriteError as error:
            raise ProjectError(str(error)) from error

        logger.info("Projet créé : %s", created)

        return self.repository.vault.read_project(created)
