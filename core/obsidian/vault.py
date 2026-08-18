import datetime
import logging
from pathlib import Path

import yaml

from core.obsidian.models import Collaborator, Project, Task


logger = logging.getLogger(__name__)


UNKNOWN_STATUS = "unknown"


def _as_optional_str(value) -> str | None:
    """Normalise une valeur de frontmatter en chaîne.

    PyYAML convertit spontanément `created: 2026-08-13` en
    `datetime.date`. Les modèles annoncent des chaînes : on
    convertit ici, en conservant le format ISO d'origine.
    """
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()

    return str(value)


class ObsidianVault:
    def __init__(self, vault_path: Path):
        self.path = vault_path.resolve()

    def exists(self) -> bool:
        return self.path.is_dir()

    def list_markdown_files(self) -> list[Path]:
        if not self.exists():
            raise FileNotFoundError(
                f"Vault introuvable : {self.path}"
            )

        return sorted(
            path
            for path in self.path.rglob("*.md")
            if ".obsidian" not in path.parts
        )

    def _check_path(self, file_path: Path) -> Path:
        """Vérifie qu'un chemin est exploitable.

        Garde-fou central : tout accès fichier passe par ici.
        """
        file_path = file_path.resolve()

        if not file_path.is_relative_to(self.path):
            raise ValueError(
                "Le fichier demandé est en dehors du Vault."
            )

        if file_path.suffix.lower() != ".md":
            raise ValueError(
                "Le fichier demandé n'est pas un fichier Markdown."
            )

        return file_path

    def _split_frontmatter(
        self,
        content: str,
    ) -> tuple[str | None, str]:
        """Sépare le frontmatter du corps du document.

        Renvoie (frontmatter_brut, corps). Le frontmatter vaut
        None quand le fichier n'en contient pas.
        """
        lines = content.splitlines()

        if len(lines) < 3 or lines[0].strip() != "---":
            return None, content

        try:
            end_index = lines.index("---", 1)
        except ValueError:
            return None, content

        frontmatter_text = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1 :])

        return frontmatter_text, body

    def read_frontmatter(self, file_path: Path) -> dict:
        file_path = self._check_path(file_path)

        content = file_path.read_text(encoding="utf-8")

        frontmatter_text, _ = self._split_frontmatter(content)

        if frontmatter_text is None:
            return {}

        try:
            data = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as error:
            # Certains fichiers du Vault ne sont pas du YAML :
            # 99-Templates/template-taches.md contient du code
            # Templater. On lève une erreur propre plutôt que de
            # laisser fuiter une exception PyYAML.
            raise ValueError(
                f"Frontmatter illisible dans : {file_path}"
            ) from error

        if data is None:
            return {}

        if not isinstance(data, dict):
            raise ValueError(
                f"Frontmatter invalide dans : {file_path}"
            )

        return data

    def safe_read_frontmatter(
        self,
        file_path: Path,
    ) -> dict | None:
        """Version tolérante de `read_frontmatter`.

        Renvoie None au lieu de lever quand un fichier est
        illisible. Indispensable pour les parcours complets du
        Vault : un seul fichier mal formé ne doit pas faire
        échouer une commande entière.
        """
        try:
            return self.read_frontmatter(file_path)
        except (ValueError, OSError) as error:
            logger.warning(
                "Fichier ignoré (%s) : %s",
                file_path,
                error,
            )
            return None

    def read_body(self, file_path: Path) -> str:
        """Renvoie le contenu du fichier, frontmatter exclu."""
        file_path = self._check_path(file_path)

        content = file_path.read_text(encoding="utf-8")

        _, body = self._split_frontmatter(content)

        return body

    def build_project(
        self,
        data: dict,
        file_path: Path,
    ) -> Project:
        """Construit un Project à partir d'un frontmatter déjà lu."""
        return Project(
            path=file_path.resolve(),
            type=data["type"],
            status=_as_optional_str(data.get("status"))
            or UNKNOWN_STATUS,
            name=_as_optional_str(data.get("name"))
            or file_path.stem,
            category=_as_optional_str(data.get("category")),
            priority=_as_optional_str(data.get("priority")),
            created=_as_optional_str(data.get("created")),
            deadline=_as_optional_str(data.get("deadline")),
            repository=_as_optional_str(data.get("repository")),
            # PyYAML relit un identifiant Discord comme un entier :
            # `_as_optional_str` le ramène en chaîne.
            discord_channel_id=_as_optional_str(
                data.get("discord_channel_id")
            ),
            discord_panel_message=_as_optional_str(
                data.get("discord_panel_message")
            ),
        )

    def build_collaborator(
        self,
        data: dict,
        file_path: Path,
    ) -> Collaborator:
        """Construit un Collaborator à partir d'un frontmatter déjà lu."""
        return Collaborator(
            path=file_path.resolve(),
            type=data["type"],
            status=_as_optional_str(data.get("status"))
            or UNKNOWN_STATUS,
            name=_as_optional_str(data.get("name"))
            or file_path.stem,
            role=_as_optional_str(data.get("role")),
            company=_as_optional_str(data.get("company")),
            discord=_as_optional_str(data.get("discord")),
            email=_as_optional_str(data.get("email")),
            github=_as_optional_str(data.get("github")),
            website=_as_optional_str(data.get("website")),
            timezone=_as_optional_str(data.get("timezone")),
            joined=_as_optional_str(data.get("joined")),
        )

    def build_task(
        self,
        data: dict,
        file_path: Path,
    ) -> Task:
        """Construit une Task à partir d'un frontmatter déjà lu."""
        return Task(
            path=file_path.resolve(),
            name=file_path.stem,
            type=data["type"],
            status=_as_optional_str(data.get("status"))
            or UNKNOWN_STATUS,
            priority=_as_optional_str(data.get("priority")),
            platform=_as_optional_str(data.get("platform")),
            project=_as_optional_str(data.get("project")),
            collaborator=_as_optional_str(
                data.get("collaborator")
            ),
            created=_as_optional_str(data.get("created")),
            deadline=_as_optional_str(data.get("deadline")),
            due=_as_optional_str(data.get("due")),
            completed=_as_optional_str(data.get("completed")),
        )

    def read_project(self, file_path: Path) -> Project:
        data = self.read_frontmatter(file_path)

        if data.get("type") != "project":
            raise ValueError(
                f"Le fichier n'est pas un projet : {file_path}"
            )

        return self.build_project(data, file_path)

    def read_collaborator(
        self,
        file_path: Path,
    ) -> Collaborator:
        data = self.read_frontmatter(file_path)

        if data.get("type") != "collaborator":
            raise ValueError(
                f"Le fichier n'est pas un collaborateur : {file_path}"
            )

        return self.build_collaborator(data, file_path)

    def read_task(self, file_path: Path) -> Task:
        data = self.read_frontmatter(file_path)

        if data.get("type") != "task":
            raise ValueError(
                f"Le fichier n'est pas une tâche : {file_path}"
            )

        return self.build_task(data, file_path)
