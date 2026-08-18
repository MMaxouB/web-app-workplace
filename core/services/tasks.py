"""Logique métier des tâches.

Séparée des commandes Discord : cette classe ne connaît ni
`ctx`, ni les Embed. Elle est donc testable sans Discord.

Le format produit reproduit fidèlement celui de
99-Templates/template-taches.md, pour que les tâches créées
depuis Discord soient indiscernables de celles créées par
Templater dans Obsidian.
"""

import datetime
import logging
import re
from dataclasses import dataclass, field

from core.obsidian.models import Task
from core.obsidian.repository import ObsidianRepository
from core.obsidian.writer import VaultWriteError, VaultWriter
from core.services.base import VaultNoteService


logger = logging.getLogger(__name__)


def _heure_de(valeur: str | None) -> datetime.time | None:
    """Heure portée par un champ `due`, ou None.

    Le Vault contient des valeurs libres (`x`, `X`) là où on
    attendrait une date : elles ne portent pas d'heure, et ce n'est
    pas une erreur.
    """
    if not valeur:
        return None

    try:
        return datetime.datetime.fromisoformat(str(valeur)).timetz()
    except ValueError:
        return None


def libelle_precedent(valeur) -> str:
    """Valeur précédente, telle qu'elle doit apparaître dans l'historique.

    `getattr(..., None)` rend None pour un champ vide, et le laisser
    tel quel écrirait « Champ `company` : `None` → … » dans une note
    que l'utilisateur relit.
    """
    return str(valeur) if valeur not in (None, "") else "vide"


# Correspondance reprise de 99-Templates/move-task.md.
STATUS_FOLDERS = {
    "active": "05-Tasks/Actives",
    "waiting": "05-Tasks/En attente",
    "completed": "05-Tasks/Terminées",
    "archived": "05-Tasks/Archives",
}

INBOX_FOLDER = "05-Tasks/_Inbox"

VALID_STATUSES = tuple(STATUS_FOLDERS)

VALID_PRIORITIES = ("critical", "high", "medium", "low")

VALID_PLATFORMS = (
    "Obsidian",
    "Code",
    "Discord",
    "Documentation",
    "Economy",
    "Cybersecurity",
    "Autre",
)

# Délais proposés par le template, avec leur décalage.
DEADLINE_OFFSETS = {
    "24h": datetime.timedelta(hours=24),
    "48h": datetime.timedelta(hours=48),
    "3j": datetime.timedelta(days=3),
    "7j": datetime.timedelta(days=7),
    "14j": datetime.timedelta(days=14),
    "1m": None,  # un mois calendaire, traité à part
}

# Caractères interdits dans un nom de fichier Obsidian.
_FORBIDDEN_IN_FILENAME = re.compile(r'[\\/:*?"<>|#^\[\]]')


# Correspondance entre champs du frontmatter et lignes du
# tableau « Informations » présent dans le corps des notes.
FIELD_TABLE_LABELS = {
    "status": "Statut",
    "priority": "Priorité",
    "platform": "Plateforme",
    "project": "Projet",
    "collaborator": "Collaborateur",
    "due": "Deadline",
    "deadline": "Délai",
}

HISTORY_SECTION = "## Historique"


class TaskError(Exception):
    """Opération impossible, avec un message destiné à l'utilisateur."""


@dataclass
class TaskUpdate:
    """Résultat d'une modification.

    Les avertissements concernent les éléments décoratifs (tableau,
    historique) qui n'ont pas pu être mis à jour. Ils n'empêchent
    jamais l'opération : le frontmatter fait foi.
    """

    task: Task
    warnings: list[str] = field(default_factory=list)


def flatten_section(texte: str) -> str:
    """Nettoie un texte destiné au corps d'une note.

    Une description saisie dans Discord peut contenir des titres
    Markdown. Collés tels quels, ils créeraient de fausses sections
    et perturberaient toutes les écritures ultérieures — c'est la
    section suivante que `prepend_to_section` viserait. On dégrade
    donc les `#` de tête en texte.
    """
    if not texte:
        return ""

    lignes = []

    for ligne in texte.strip().splitlines():
        nettoyee = ligne.rstrip()

        if nettoyee.lstrip().startswith("#"):
            nettoyee = nettoyee.lstrip().lstrip("#").strip()

        lignes.append(nettoyee)

    return "\n".join(lignes).strip()


def sanitize_filename(name: str) -> str:
    """Rend un titre utilisable comme nom de fichier."""
    cleaned = _FORBIDDEN_IN_FILENAME.sub("", name)

    cleaned = " ".join(cleaned.split()).strip(". ")

    if not cleaned:
        raise TaskError("Le nom de la tâche est vide.")

    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()

    return cleaned


def add_one_month(moment: datetime.datetime) -> datetime.datetime:
    """Ajoute un mois calendaire, comme le « P1M » de Templater."""
    year = moment.year + (moment.month // 12)
    month = moment.month % 12 + 1

    day = min(moment.day, _days_in_month(year, month))

    return moment.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)

    return (next_month - datetime.timedelta(days=1)).day


def compute_due(
    deadline_label: str,
    now: datetime.datetime,
) -> datetime.datetime:
    if deadline_label not in DEADLINE_OFFSETS:
        raise TaskError(
            f"Délai inconnu : « {deadline_label} ». "
            f"Choix possibles : {', '.join(DEADLINE_OFFSETS)}."
        )

    if deadline_label == "1m":
        return add_one_month(now)

    return now + DEADLINE_OFFSETS[deadline_label]


def format_iso(moment: datetime.datetime) -> str:
    """Format « YYYY-MM-DDTHH:mm:ssZ » de Templater."""
    return moment.isoformat(timespec="seconds")


def format_display(moment: datetime.datetime) -> str:
    """Format « DD/MM/YYYY HH:mm » utilisé dans le corps."""
    return moment.strftime("%d/%m/%Y %H:%M")


OBJECTIF_PAR_DEFAUT = "Décrire précisément ce qui doit être accompli."


def build_task_content(
    *,
    title: str,
    status: str,
    priority: str,
    platform: str,
    project: str,
    collaborator: str,
    deadline_label: str,
    now: datetime.datetime,
    objectif: str = "",
) -> str:
    """Produit une note de tâche au format du template Obsidian.

    `objectif` remplit la section « ## Objectif » quand la fenêtre
    de création l'a demandé. Vide, la note garde l'invite du
    template : une section vide se remplit dans Obsidian, une
    section absente casse la structure attendue.
    """
    due = compute_due(deadline_label, now)

    objectif = flatten_section(objectif) or OBJECTIF_PAR_DEFAUT

    return f"""---
type: task
status: {status}
priority: {priority}
platform: "{platform}"
project: "{project}"
collaborator: "{collaborator}"
created: {format_iso(now)}
deadline: "{deadline_label}"
due: {format_iso(due)}
completed:
---

# {title}

## Informations

| Propriété | Valeur |
|---|---|
| Statut | `{status}` |
| Priorité | `{priority}` |
| Plateforme | {platform} |
| Projet | {project} |
| Collaborateur | {collaborator} |
| Créée le | {format_display(now)} |
| Délai | {deadline_label} |
| Deadline | {format_display(due)} |

## Objectif

{objectif}

## Checklist

- [ ]

## Résultat attendu

Décrire le résultat attendu.

## Ressources

-

## Notes

-

## Historique

### {format_display(now)}

- Tâche créée depuis la web app.
"""


class TaskService(VaultNoteService):
    TABLE_LABELS = FIELD_TABLE_LABELS
    HISTORY_GROUPED = False
    KIND_LABEL = "tâche"

    def display_value(self, key: str, value: str) -> str:
        # Le tableau affiche les échéances en clair, pas en ISO.
        if key == "due" and value:
            try:
                return format_display(
                    datetime.datetime.fromisoformat(value)
                )
            except ValueError:
                return value

        return value

    # =====================================================
    # Résolution
    # =====================================================

    def resolve_task(self, name: str | Task) -> Task:
        """Retrouve une tâche, ou explique pourquoi c'est impossible.

        En cas d'ambiguïté, on refuse : agir sur la mauvaise note
        serait pire que ne rien faire.

        Une tâche déjà résolue est acceptée telle quelle. L'API web
        désigne les notes par leur chemin, qui lève l'ambiguïté à la
        source ; Discord n'avait que des noms saisis à la main.
        """
        if isinstance(name, Task):
            return name

        task = self.repository.find_task(name)

        if task is not None:
            return task

        candidates = self.repository.find_matching_tasks(name)

        if not candidates:
            raise TaskError(
                f"Aucune tâche ne correspond à « {name} »."
            )

        noms = "\n".join(
            f"• {candidate.name}" for candidate in candidates
        )

        raise TaskError(
            f"Plusieurs tâches correspondent à « {name} » :\n"
            f"{noms}\n\nPrécise ta recherche."
        )

    # =====================================================
    # Modifications
    # =====================================================

    def change_status(self, name: str, status: str) -> TaskUpdate:
        """Change le statut et range la tâche dans le bon dossier."""
        status = status.strip().casefold()

        if status not in VALID_STATUSES:
            raise TaskError(
                f"Statut invalide : « {status} ». "
                f"Valeurs acceptées : {', '.join(VALID_STATUSES)}."
            )

        task = self.resolve_task(name)

        if task.status == status:
            raise TaskError(
                f"« {task.name} » est déjà au statut « {status} »."
            )

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                task.path,
                "status",
                status,
            )

            # Le Vault date les tâches terminées.
            if status == "completed" and not task.completed:
                self.writer.set_frontmatter_field(
                    task.path,
                    "completed",
                    datetime.date.today().isoformat(),
                )

            self.record(
                warnings,
                task.path,
                "status",
                status,
                f"Statut passé de `{task.status}` à "
                f"`{status}` (depuis la web app).",
            )

            destination = self.vault_path / STATUS_FOLDERS[status]

            new_path = self.writer.move_note(task.path, destination)
        except VaultWriteError as error:
            raise TaskError(str(error)) from error

        logger.info(
            "Statut de « %s » : %s -> %s",
            task.name,
            task.status,
            status,
        )

        return TaskUpdate(
            self.repository.vault.read_task(new_path),
            warnings,
        )

    def change_priority(
        self,
        name: str,
        priority: str,
    ) -> TaskUpdate:
        priority = priority.strip().casefold()

        if priority not in VALID_PRIORITIES:
            raise TaskError(
                f"Priorité invalide : « {priority} ». "
                f"Valeurs acceptées : {', '.join(VALID_PRIORITIES)}."
            )

        task = self.resolve_task(name)

        if task.priority == priority:
            raise TaskError(
                f"« {task.name} » est déjà en priorité "
                f"« {priority} »."
            )

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                task.path,
                "priority",
                priority,
            )

            self.record(
                warnings,
                task.path,
                "priority",
                priority,
                f"Priorité passée de `{task.priority}` à "
                f"`{priority}` (depuis la web app).",
            )
        except VaultWriteError as error:
            raise TaskError(str(error)) from error

        logger.info(
            "Priorité de « %s » : %s -> %s",
            task.name,
            task.priority,
            priority,
        )

        return TaskUpdate(
            self.repository.vault.read_task(task.path),
            warnings,
        )

    def set_field(
        self,
        name: str,
        key: str,
        value: str,
    ) -> TaskUpdate:
        """Modifie un champ libre du frontmatter d'une tâche."""
        editable = (
            "platform",
            "project",
            "collaborator",
            "due",
            "deadline",
        )

        key = key.strip().casefold()

        if key not in editable:
            raise TaskError(
                f"Champ non modifiable : « {key} ». "
                f"Champs autorisés : {', '.join(editable)}."
            )

        if key == "platform" and value not in VALID_PLATFORMS:
            raise TaskError(
                f"Plateforme inconnue : « {value} ». "
                f"Choix : {', '.join(VALID_PLATFORMS)}."
            )

        task = self.resolve_task(name)

        previous = getattr(task, key, None)

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(task.path, key, value)

            self.record(
                warnings,
                task.path,
                key,
                value,
                f"Champ `{key}` : `{libelle_precedent(previous)}` → `{value}` "
                "(depuis la web app).",
            )
        except VaultWriteError as error:
            raise TaskError(str(error)) from error

        logger.info(
            "Champ « %s » de « %s » -> %r",
            key,
            task.name,
            value,
        )

        return TaskUpdate(
            self.repository.vault.read_task(task.path),
            warnings,
        )

    def set_deadline(
        self,
        name: str,
        deadline_label: str,
        now: datetime.datetime | None = None,
    ) -> TaskUpdate:
        """Change le délai ET recalcule l'échéance.

        Les deux champs vont de pair : `deadline` garde le libellé
        choisi (« 14j »), `due` porte la date correspondante. Ne
        modifier que l'un des deux les rendrait contradictoires.
        """
        if deadline_label not in DEADLINE_OFFSETS:
            raise TaskError(
                f"Délai inconnu : « {deadline_label} ». "
                f"Choix possibles : {', '.join(DEADLINE_OFFSETS)}."
            )

        task = self.resolve_task(name)

        if now is None:
            now = datetime.datetime.now().astimezone()

        due = compute_due(deadline_label, now)

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_field(
                task.path,
                "deadline",
                deadline_label,
            )

            self.writer.set_frontmatter_field(
                task.path,
                "due",
                format_iso(due),
            )

            self.record(
                warnings,
                task.path,
                "deadline",
                deadline_label,
                f"Délai : `{task.deadline}` → `{deadline_label}`, "
                f"échéance au {format_display(due)} "
                "(depuis la web app).",
            )

            self._keep_table(
                warnings,
                task.path,
                "due",
                format_iso(due),
            )
        except VaultWriteError as error:
            raise TaskError(str(error)) from error

        logger.info(
            "Délai de « %s » : %s -> %s",
            task.name,
            task.deadline,
            deadline_label,
        )

        return TaskUpdate(
            self.repository.vault.read_task(task.path),
            warnings,
        )

    def set_due_date(
        self,
        name: str | Task,
        date_iso: str,
        now: datetime.datetime | None = None,
    ) -> TaskUpdate:
        """Fixe l'échéance à une date précise (vue calendrier).

        `set_deadline` part d'un libellé (« 7j ») et en déduit la
        date. Ici c'est l'inverse : glisser une carte sur le 25 août
        donne la date, dont on déduit le libellé.

        Le libellé garde le format du Vault — un nombre de jours
        suivi de « j » — même quand il ne fait pas partie des délais
        proposés à la création. `deadline: 9j` reste lisible et
        cohérent avec `deadline: 7j` ; laisser l'ancien libellé le
        rendrait contradictoire avec la nouvelle date.

        L'heure de l'échéance d'origine est conservée : seule la
        date change, comme le geste le laisse attendre.
        """
        task = self.resolve_task(name)

        if now is None:
            now = datetime.datetime.now().astimezone()

        try:
            jour = datetime.date.fromisoformat(date_iso[:10])
        except ValueError as error:
            raise TaskError(
                f"Date illisible : « {date_iso} ». "
                "Format attendu : AAAA-MM-JJ."
            ) from error

        ancienne = _heure_de(task.due)

        due = datetime.datetime.combine(
            jour,
            ancienne or now.timetz(),
        )

        if due.tzinfo is None:
            due = due.replace(tzinfo=now.tzinfo)

        ecart = (jour - now.date()).days

        # Une échéance dans le passé n'a pas de délai : on garde le
        # libellé tel quel plutôt que d'écrire « -3j ».
        libelle = f"{ecart}j" if ecart >= 0 else (task.deadline or "")

        warnings: list[str] = []

        try:
            self.writer.set_frontmatter_fields(
                task.path,
                {"deadline": libelle, "due": format_iso(due)},
            )

            self.record(
                warnings,
                task.path,
                "deadline",
                libelle,
                f"Échéance déplacée au {format_display(due)} "
                "(depuis la web app).",
            )

            self._keep_table(
                warnings,
                task.path,
                "due",
                format_iso(due),
            )
        except VaultWriteError as error:
            raise TaskError(str(error)) from error

        logger.info(
            "Échéance de « %s » : %s -> %s",
            task.name,
            task.due,
            format_iso(due),
        )

        return TaskUpdate(
            self.repository.vault.read_task(task.path),
            warnings,
        )

    def _keep_table(
        self,
        warnings: list[str],
        path,
        key: str,
        value: str,
    ) -> None:
        """Synchronise une ligne de tableau sans toucher l'historique."""
        warning = self.sync_table(path, key, value)

        if warning:
            warnings.append(warning)

    # =====================================================
    # Création
    # =====================================================

    def create_task(
        self,
        *,
        title: str,
        status: str = "active",
        priority: str = "medium",
        platform: str = "Autre",
        project: str = "",
        collaborator: str = "Moi",
        deadline_label: str = "7j",
        now: datetime.datetime | None = None,
        objectif: str = "",
        dossier: str | None = None,
    ) -> Task:
        status = status.strip().casefold()
        priority = priority.strip().casefold()

        if status not in VALID_STATUSES:
            raise TaskError(
                f"Statut invalide : « {status} ». "
                f"Valeurs acceptées : {', '.join(VALID_STATUSES)}."
            )

        if priority not in VALID_PRIORITIES:
            raise TaskError(
                f"Priorité invalide : « {priority} ». "
                f"Valeurs acceptées : {', '.join(VALID_PRIORITIES)}."
            )

        if platform not in VALID_PLATFORMS:
            raise TaskError(
                f"Plateforme inconnue : « {platform} ». "
                f"Choix : {', '.join(VALID_PLATFORMS)}."
            )

        filename = sanitize_filename(title)

        if self.repository.find_task(filename) is not None:
            raise TaskError(
                f"Une tâche « {filename} » existe déjà."
            )

        if now is None:
            now = datetime.datetime.now().astimezone()

        content = build_task_content(
            title=filename,
            status=status,
            priority=priority,
            platform=platform,
            project=project,
            collaborator=collaborator,
            deadline_label=deadline_label,
            now=now,
            objectif=objectif,
        )

        # `dossier` sert à la capture rapide, qui dépose dans
        # `_Inbox` une tâche par ailleurs active. Le décalage entre
        # le statut et le dossier est voulu : c'est lui qui signale
        # qu'elle reste à trier, et le premier changement de statut
        # la range au bon endroit.
        destination = (
            self.vault_path
            / (dossier or STATUS_FOLDERS[status])
            / f"{filename}.md"
        )

        try:
            created = self.writer.create_note(destination, content)
        except VaultWriteError as error:
            raise TaskError(str(error)) from error

        logger.info("Tâche créée : %s", created)

        return self.repository.vault.read_task(created)

    def capture(
        self,
        title: str,
        detail: str = "",
        now: datetime.datetime | None = None,
    ) -> Task:
        """Capture rapide : une idée déposée sans rien décider (§17).

        Tout l'intérêt de l'Inbox est de ne poser **aucune
        question**. Une pensée qu'il faut classer avant de l'écrire
        est une pensée qu'on n'écrit pas. Le projet, la priorité et
        la plateforme se règlent plus tard, depuis la vue
        « Nettoyage » qui liste précisément ce qui reste à trier.
        """
        return self.create_task(
            title=title,
            objectif=detail,
            dossier=INBOX_FOLDER,
            now=now,
        )
