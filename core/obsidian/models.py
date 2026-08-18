from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    path: Path
    type: str
    status: str
    name: str
    category: str | None
    priority: str | None
    created: str | None
    deadline: str | None
    repository: str | None

    # Lien vers le salon Discord du projet. Ces deux champs sont
    # écrits par le bot, absents des fiches créées à la main, et
    # placés en dernier pour que toute construction existante de
    # Project reste valide.
    discord_channel_id: str | None = None
    discord_panel_message: str | None = None

    @property
    def filename(self) -> str:
        """Nom du fichier sans extension.

        Peut différer de `name` : le projet « AI Video Editor »
        est stocké dans « AI-Powered Video Editor.md ».
        """
        return self.path.stem


@dataclass(frozen=True)
class Collaborator:
    path: Path
    type: str
    status: str
    name: str
    role: str | None
    company: str | None
    discord: str | None
    email: str | None
    github: str | None
    website: str | None
    timezone: str | None
    joined: str | None

    @property
    def filename(self) -> str:
        """Nom du fichier sans extension.

        Peut différer de `name` : le collaborateur « parth »
        est stocké dans « ZIPZOP.md ».
        """
        return self.path.stem


@dataclass(frozen=True)
class Task:
    path: Path
    name: str
    type: str
    status: str
    priority: str | None
    platform: str | None
    project: str | None
    collaborator: str | None
    created: str | None
    deadline: str | None
    due: str | None
    completed: str | None

    @property
    def filename(self) -> str:
        """Nom du fichier sans extension.

        Pour une tâche, c'est aussi son identifiant : le Vault
        ne stocke pas de champ `name` dans le frontmatter.
        """
        return self.path.stem

    @property
    def is_open(self) -> bool:
        """Une tâche ouverte n'est ni terminée ni archivée."""
        return self.status not in ("completed", "archived")

    @property
    def is_inbox(self) -> bool:
        """Tâche déposée par la capture rapide, en attente de tri.

        Le dossier fait foi, pas le statut : une capture est active
        dès sa création, mais tant qu'elle est dans `_Inbox`, ni son
        projet ni sa priorité n'ont été choisis.
        """
        return self.path.parent.name == "_Inbox"
