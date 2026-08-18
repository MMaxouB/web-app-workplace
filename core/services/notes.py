"""Ajout de notes libres aux fiches du Vault.

Séparation volontaire :

- « ## Notes »      reçoit ce que l'utilisateur écrit
- « ## Historique » reste réservé au journal automatique du bot

L'insertion se fait en tête de section, comme le reste du Vault,
et ne touche à aucune autre ligne du fichier.
"""

import datetime
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from core.obsidian.repository import ObsidianRepository
from core.obsidian.writer import VaultWriteError, VaultWriter
from core.utils.text import normalize


logger = logging.getLogger(__name__)


NOTE_SECTION = "## Notes"

# Types de fiches acceptés, avec leurs synonymes français.
KIND_ALIASES = {
    "task": "task",
    "tache": "task",
    "taches": "task",
    "project": "project",
    "projet": "project",
    "projets": "project",
    "collab": "collaborator",
    "collaborator": "collaborator",
    "collaborateur": "collaborator",
}

KIND_LABELS = {
    "task": "tâche",
    "project": "projet",
    "collaborator": "collaborateur",
}

_QUOTED = re.compile(r'^["“]([^"”]+)["”]\s+(.+)$', re.DOTALL)


class NoteError(Exception):
    """Opération impossible, avec un message pour l'utilisateur."""


@dataclass
class NoteResult:
    kind: str
    name: str
    path: Path
    text: str
    genre: str = "Note"


def resolve_kind(raw: str) -> str | None:
    return KIND_ALIASES.get(normalize(raw))


def split_target_and_text(raw: str) -> tuple[str, str]:
    """Sépare le nom de la fiche du texte de la note.

    Deux écritures acceptées :

        !note projet "AI Video Editor" = le compositeur fonctionne
        !note projet "AI Video Editor" le compositeur fonctionne
    """
    raw = raw.strip()

    if not raw:
        return "", ""

    if "=" in raw:
        name, _, text = raw.partition("=")

        return (
            name.strip().strip("\"'“”").strip(),
            text.strip(),
        )

    quoted = _QUOTED.match(raw)

    if quoted:
        return quoted.group(1).strip(), quoted.group(2).strip()

    return "", ""


# Natures de note proposées par l'interface (§15). « Note » est la
# valeur par défaut et reste muette : préfixer chaque puce d'un
# « Note — » n'apprendrait rien à personne.
NOTE_TYPES = (
    "Note",
    "Décision",
    "Idée",
    "Information",
    "Compte-rendu",
)

TYPE_NEUTRE = "Note"


def resolve_type(raw: str | None) -> str:
    """Ramène une nature saisie librement à l'une des valeurs connues."""
    if not raw:
        return TYPE_NEUTRE

    for connu in NOTE_TYPES:
        if normalize(connu) == normalize(raw):
            return connu

    return TYPE_NEUTRE


def format_note(
    text: str,
    now: datetime.datetime,
    author: str = "",
    genre: str = "",
) -> str:
    """Une puce lisible et datée, sans casser la structure du Vault.

    Les lignes suivantes sont indentées de deux espaces : elles
    restent rattachées à la puce, et un « ## Titre » collé dans un
    message ne peut pas créer une fausse section qui perturberait
    les écritures ultérieures.

    La nature de la note (décision, idée…) est portée en tête de
    puce, en gras. Relire une fiche six mois plus tard, c'est
    surtout chercher les décisions au milieu du reste.
    """
    horodatage = now.strftime("%d/%m/%Y %H:%M")

    signature = f"{horodatage}, depuis la web app"

    if author:
        signature += f" — {author}"

    lignes = [
        ligne.rstrip()
        for ligne in text.strip().splitlines()
        if ligne.strip()
    ]

    if not lignes:
        return f"- _({signature})_"

    genre = resolve_type(genre)

    prefixe = f"**{genre}** — " if genre != TYPE_NEUTRE else ""

    premiere = f"- {prefixe}{lignes[0]}"

    suivantes = [f"  {ligne}" for ligne in lignes[1:]]

    if suivantes:
        return "\n".join([premiere, *suivantes]) + (
            f"\n  _({signature})_"
        )

    return f"{premiere} _({signature})_"


class NoteService:
    def __init__(
        self,
        repository: ObsidianRepository,
        writer: VaultWriter,
        task_service,
        project_service,
        collaborator_service,
    ):
        self.repository = repository
        self.writer = writer
        self.task_service = task_service
        self.project_service = project_service
        self.collaborator_service = collaborator_service

    def _resolve(self, kind: str, name: str):
        """Retrouve la fiche visée via le service correspondant."""
        try:
            if kind == "task":
                found = self.task_service.resolve_task(name)

                return found.name, found.path

            if kind == "project":
                found = self.project_service.resolve_project(name)

                return found.name, found.path

            found = self.collaborator_service.resolve_collaborator(
                name
            )

            return found.name, found.path
        except Exception as error:
            # Les trois services lèvent des erreurs distinctes mais
            # portent toutes un message déjà destiné à l'utilisateur.
            raise NoteError(str(error)) from error

    def add_note(
        self,
        kind: str,
        name: str,
        text: str,
        *,
        author: str = "",
        genre: str = "",
        now: datetime.datetime | None = None,
    ) -> NoteResult:
        resolved_kind = resolve_kind(kind)

        if resolved_kind is None:
            raise NoteError(
                f"Type inconnu : « {kind} ». "
                "Utilise `task`, `project` ou `collab`."
            )

        if not name:
            raise NoteError("Précise la fiche visée.")

        if not text.strip():
            raise NoteError("La note est vide.")

        note_name, path = self._resolve(resolved_kind, name)

        if now is None:
            now = datetime.datetime.now().astimezone()

        bullet = format_note(text.strip(), now, author, genre)

        try:
            self.writer.prepend_to_section(
                path,
                NOTE_SECTION,
                bullet,
            )
        except VaultWriteError as error:
            raise NoteError(
                f"Note non ajoutée : {error}"
            ) from error

        logger.info(
            "%s ajoutée à %s « %s » par %s",
            resolve_type(genre),
            KIND_LABELS[resolved_kind],
            note_name,
            author or "inconnu",
        )

        return NoteResult(
            kind=resolved_kind,
            name=note_name,
            path=path,
            text=text.strip(),
            genre=resolve_type(genre),
        )
