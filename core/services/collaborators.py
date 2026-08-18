"""Logique métier des collaborateurs.

Suit 99-Templates/template-collaborateur.md. Contrairement aux
fiches projet, les fiches collaborateur affichent les valeurs
brutes dans leur tableau (« active » et non « Actif ») : on
reproduit cet usage.

Les fiches ont deux tableaux, « Informations » et « Contacts ».
Les libellés étant distincts, une simple recherche par libellé
suffit à viser le bon.
"""

import datetime
import logging
from dataclasses import dataclass, field

from core.obsidian.models import Collaborator
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
    "active": "01-Collaborateurs/Actifs",
    "waiting": "01-Collaborateurs/En attente",
    "completed": "01-Collaborateurs/Terminés",
}

VALID_STATUSES = tuple(STATUS_FOLDERS)

FIELD_TABLE_LABELS = {
    "name": "Nom",
    "role": "Rôle",
    "status": "Statut",
    "company": "Entreprise",
    "timezone": "Fuseau horaire",
    "discord": "Discord",
    "email": "Email",
    "github": "GitHub",
    "website": "Website",
}

EDITABLE_FIELDS = (
    "role",
    "company",
    "discord",
    "email",
    "github",
    "website",
    "timezone",
)

HISTORY_SECTION = "## Historique"


class CollaboratorError(Exception):
    """Opération impossible, avec un message pour l'utilisateur."""


@dataclass
class CollaboratorUpdate:
    collaborator: Collaborator
    warnings: list[str] = field(default_factory=list)


def build_collaborator_content(
    *,
    name: str,
    status: str,
    role: str,
    company: str,
    discord: str,
    email: str,
    github: str,
    website: str,
    timezone: str,
    now: datetime.datetime,
) -> str:
    joined = now.date().isoformat()

    return f"""---
type: collaborator
status: {status}
name: {name}
role: {role}
company: {company}
discord: {discord}
email: {email}
github: {github}
website: {website}
timezone: {timezone}
joined: {joined}
---

# {name}

## Informations

| Champ          | Information |
| -------------- | ----------- |
| Nom            | {name} |
| Rôle           | {role} |
| Statut         | {status} |
| Entreprise     | {company} |
| Fuseau horaire | {timezone} |

## Contacts

| Plateforme | Contact  |
| ---------- | -------- |
| Discord    | {discord} |
| Email      | {email} |
| GitHub     | {github} |
| Website    | {website} |

## Projets

-

## Responsabilités

-

## Compétences

-

## Disponibilité

-

## Notes

-

## Historique

### {joined}
- Fiche créée depuis la web app.
"""


class CollaboratorService(VaultNoteService):
    TABLE_LABELS = FIELD_TABLE_LABELS
    HISTORY_GROUPED = True
    KIND_LABEL = "fiche collaborateur"

    # =====================================================
    # Résolution
    # =====================================================

    def resolve_collaborator(
        self,
        name: str | Collaborator,
    ) -> Collaborator:
        # Une fiche déjà résolue est acceptée telle quelle : l'API
        # web désigne les notes par leur chemin, sans ambiguïté.
        if isinstance(name, Collaborator):
            return name

        found = self.repository.find_collaborator(name)

        if found is None:
            found = self.repository.find_collaborator_by_discord(
                name
            )

        if found is not None:
            return found

        candidates = (
            self.repository.find_matching_collaborators(name)
        )

        if not candidates:
            raise CollaboratorError(
                f"Aucun collaborateur ne correspond à « {name} »."
            )

        noms = "\n".join(
            f"• {candidate.name}" for candidate in candidates
        )

        raise CollaboratorError(
            f"Plusieurs collaborateurs correspondent à "
            f"« {name} » :\n{noms}\n\nPrécise ta recherche."
        )

    # =====================================================
    # Modifications
    # =====================================================

    def change_status(
        self,
        name: str,
        status: str,
    ) -> CollaboratorUpdate:
        status = status.strip().casefold()

        if status not in VALID_STATUSES:
            raise CollaboratorError(
                f"Statut invalide : « {status} ». "
                f"Valeurs acceptées : {', '.join(VALID_STATUSES)}."
            )

        collaborator = self.resolve_collaborator(name)

        if collaborator.status == status:
            raise CollaboratorError(
                f"« {collaborator.name} » est déjà au statut "
                f"« {status} »."
            )

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                collaborator.path,
                "status",
                status,
            )

            self.record(
                warnings,
                collaborator.path,
                "status",
                status,
                f"Statut passé de `{collaborator.status}` à "
                f"`{status}` (depuis la web app).",
            )

            destination = self.vault_path / STATUS_FOLDERS[status]

            new_path = self.writer.move_note(
                collaborator.path,
                destination,
            )
        except VaultWriteError as error:
            raise CollaboratorError(str(error)) from error

        logger.info(
            "Statut du collaborateur « %s » : %s -> %s",
            collaborator.name,
            collaborator.status,
            status,
        )

        return CollaboratorUpdate(
            self.repository.vault.read_collaborator(new_path),
            warnings,
        )

    def set_field(
        self,
        name: str,
        key: str,
        value: str,
    ) -> CollaboratorUpdate:
        key = key.strip().casefold()

        if key not in EDITABLE_FIELDS:
            raise CollaboratorError(
                f"Champ non modifiable : « {key} ». "
                f"Champs autorisés : {', '.join(EDITABLE_FIELDS)}."
            )

        collaborator = self.resolve_collaborator(name)

        previous = getattr(collaborator, key, None)

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                collaborator.path,
                key,
                value,
            )

            self.record(
                warnings,
                collaborator.path,
                key,
                value,
                f"Champ `{key}` : `{libelle_precedent(previous)}` → `{value}` "
                "(depuis la web app).",
            )
        except VaultWriteError as error:
            raise CollaboratorError(str(error)) from error

        return CollaboratorUpdate(
            self.repository.vault.read_collaborator(
                collaborator.path
            ),
            warnings,
        )

    # =====================================================
    # Création
    # =====================================================

    def create_collaborator(
        self,
        *,
        name: str,
        status: str = "active",
        role: str = "",
        company: str = "",
        discord: str = "",
        email: str = "",
        github: str = "",
        website: str = "",
        timezone: str = "",
        now: datetime.datetime | None = None,
    ) -> Collaborator:
        status = status.strip().casefold()

        if status not in VALID_STATUSES:
            raise CollaboratorError(
                f"Statut invalide : « {status} ». "
                f"Valeurs acceptées : {', '.join(VALID_STATUSES)}."
            )

        try:
            filename = sanitize_filename(name)
        except TaskError as error:
            raise CollaboratorError(str(error)) from error

        if self.repository.find_collaborator(filename) is not None:
            raise CollaboratorError(
                f"Un collaborateur « {filename} » existe déjà."
            )

        if discord:
            existing = (
                self.repository.find_collaborator_by_discord(
                    discord
                )
            )

            if existing is not None:
                raise CollaboratorError(
                    f"Le pseudo Discord « {discord} » est déjà "
                    f"associé à « {existing.name} »."
                )

        if now is None:
            now = datetime.datetime.now().astimezone()

        content = build_collaborator_content(
            name=filename,
            status=status,
            role=role,
            company=company,
            discord=discord,
            email=email,
            github=github,
            website=website,
            timezone=timezone,
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
            raise CollaboratorError(str(error)) from error

        logger.info("Collaborateur créé : %s", created)

        return self.repository.vault.read_collaborator(created)
