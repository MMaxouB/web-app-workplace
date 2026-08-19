import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.obsidian.models import (
    Collaborator,
    Knowledge,
    Note,
    Project,
    Task,
)
from core.obsidian.vault import ObsidianVault
from core.utils.text import contains, matches_exactly


logger = logging.getLogger(__name__)


OPEN_STATUSES = ("active", "waiting")


@dataclass(frozen=True)
class TaskStats:
    """Compteurs d'un lot de tâches.

    Sert aux panneaux et au tableau de bord, qui affichent les
    mêmes chiffres pour un projet ou pour le Vault entier.
    """

    total: int = 0
    open: int = 0
    urgent: int = 0
    waiting: int = 0
    completed: int = 0
    archived: int = 0


# Une tâche « urgente » est ouverte ET de priorité haute ou
# critique : une tâche critique déjà terminée n'alerte plus.
URGENT_PRIORITIES = ("critical", "high")


def is_urgent(task: Task) -> bool:
    """Définition unique de l'urgence.

    Partagée par les compteurs et par la liste du tableau de bord,
    pour qu'un chiffre annoncé corresponde toujours aux tâches
    effectivement affichées.
    """
    return (
        task.is_open
        and (task.priority or "").casefold() in URGENT_PRIORITIES
    )


@dataclass(frozen=True)
class ProjectStats:
    """Répartition des projets par statut."""

    total: int = 0
    active: int = 0
    waiting: int = 0
    completed: int = 0
    archived: int = 0


def count_projects(projects: list[Project]) -> ProjectStats:
    counts = {
        "active": 0,
        "waiting": 0,
        "completed": 0,
        "archived": 0,
    }

    for project in projects:
        status = (project.status or "").casefold()

        if status in counts:
            counts[status] += 1

    return ProjectStats(total=len(projects), **counts)


@dataclass(frozen=True)
class CollaboratorStats:
    """Répartition des collaborateurs par statut."""

    total: int = 0
    active: int = 0
    waiting: int = 0
    completed: int = 0


def count_collaborators(
    collaborators: list[Collaborator],
) -> CollaboratorStats:
    counts = {"active": 0, "waiting": 0, "completed": 0}

    for collaborator in collaborators:
        status = (collaborator.status or "").casefold()

        if status in counts:
            counts[status] += 1

    return CollaboratorStats(total=len(collaborators), **counts)


@dataclass(frozen=True)
class VaultContents:
    """Toutes les notes typées du Vault, triées par type.

    Renvoyé par `_collect_all()`. Un objet nommé plutôt qu'un
    n-uplet : le Vault a gagné deux types de notes après les trois
    fiches d'origine, et il en gagnera d'autres. Ajouter une liste
    ne doit pas obliger à retoucher chaque appelant pour décaler un
    dépaquetage.
    """

    projects: list[Project] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    collaborators: list[Collaborator] = field(default_factory=list)
    knowledge: list[Knowledge] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


@dataclass(frozen=True)
class Workspace:
    """Photographie du Vault à un instant donné.

    Construite en un seul parcours par type de note : le tableau
    de bord affiche beaucoup de chiffres, il ne doit pas relire le
    Vault une fois par ligne.

    Les trois listes complètes sont conservées pour la même
    raison : les vues d'analyse (santé, échéances, graphiques)
    travaillent sur les mêmes notes, et un second parcours du Vault
    par écran serait du gaspillage pur.
    """

    projects: ProjectStats
    tasks: TaskStats
    urgent: list[Task] = field(default_factory=list)
    collaborators: CollaboratorStats = field(
        default_factory=CollaboratorStats
    )
    all_projects: list[Project] = field(default_factory=list)
    all_tasks: list[Task] = field(default_factory=list)
    all_collaborators: list[Collaborator] = field(
        default_factory=list
    )


def count_tasks(tasks: list[Task]) -> TaskStats:
    counts = {
        "open": 0,
        "urgent": 0,
        "waiting": 0,
        "completed": 0,
        "archived": 0,
    }

    for task in tasks:
        status = (task.status or "").casefold()

        if status == "completed":
            counts["completed"] += 1
        elif status == "archived":
            counts["archived"] += 1

        if not task.is_open:
            continue

        counts["open"] += 1

        if status == "waiting":
            counts["waiting"] += 1

        if is_urgent(task):
            counts["urgent"] += 1

    return TaskStats(total=len(tasks), **counts)


@dataclass
class SearchResults:
    """Résultat d'une recherche transversale dans le Vault."""

    query: str
    projects: list[Project] = field(default_factory=list)
    collaborators: list[Collaborator] = field(
        default_factory=list
    )
    tasks: list[Task] = field(default_factory=list)
    knowledge: list[Knowledge] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.projects)
            + len(self.collaborators)
            + len(self.tasks)
            + len(self.knowledge)
            + len(self.notes)
        )

    @property
    def is_empty(self) -> bool:
        return self.total == 0


class ObsidianRepository:
    def __init__(self, vault: ObsidianVault):
        self.vault = vault

    def _data_files(self) -> list[Path]:
        return [
            path
            for path in self.vault.list_markdown_files()
            if "99-Templates" not in path.parts
        ]

    def _collect(self, expected_type: str) -> list[tuple[dict, Path]]:
        """Parcourt le Vault et renvoie les notes d'un type donné.

        Un seul passage disque par fichier, et les fichiers
        illisibles sont ignorés sans faire échouer le parcours.
        """
        collected = []

        for file_path in self._data_files():
            data = self.vault.safe_read_frontmatter(file_path)

            if data is None:
                continue

            if data.get("type") != expected_type:
                continue

            collected.append((data, file_path))

        return collected

    def _collect_all(self) -> VaultContents:
        """Lit le Vault une seule fois et trie les notes par type.

        `_collect` ne rend qu'un type : l'appeler une fois par type
        relit et re-parse chaque note autant de fois. Sur le Vault
        réel, le tableau de bord passait ainsi de 18 à 54 ms pour un
        résultat identique. Tout ce qui a besoin de plusieurs types
        à la fois passe donc par ici.

        Les types inconnus sont ignorés sans bruit : c'est ce qui a
        permis aux connaissances et aux notes d'exister dans le
        Vault des semaines avant que l'application ne les lise.
        """
        contenu = VaultContents()

        for file_path in self._data_files():
            data = self.vault.safe_read_frontmatter(file_path)

            if data is None:
                continue

            match data.get("type"):
                case "project":
                    contenu.projects.append(
                        self.vault.build_project(data, file_path)
                    )
                case "task":
                    contenu.tasks.append(
                        self.vault.build_task(data, file_path)
                    )
                case "collaborator":
                    contenu.collaborators.append(
                        self.vault.build_collaborator(
                            data,
                            file_path,
                        )
                    )
                case "knowledge":
                    contenu.knowledge.append(
                        self.vault.build_knowledge(data, file_path)
                    )
                case "note":
                    contenu.notes.append(
                        self.vault.build_note(data, file_path)
                    )

        return contenu

    # =====================================================
    # Listes
    # =====================================================

    def get_projects(self) -> list[Project]:
        return [
            self.vault.build_project(data, file_path)
            for data, file_path in self._collect("project")
        ]

    def get_collaborators(self) -> list[Collaborator]:
        return [
            self.vault.build_collaborator(data, file_path)
            for data, file_path in self._collect("collaborator")
        ]

    def get_tasks(self) -> list[Task]:
        return [
            self.vault.build_task(data, file_path)
            for data, file_path in self._collect("task")
        ]

    def get_knowledge(self) -> list[Knowledge]:
        return [
            self.vault.build_knowledge(data, file_path)
            for data, file_path in self._collect("knowledge")
        ]

    def get_notes(self) -> list[Note]:
        return [
            self.vault.build_note(data, file_path)
            for data, file_path in self._collect("note")
        ]

    # =====================================================
    # Filtres
    # =====================================================

    def get_tasks_by_status(self, status: str) -> list[Task]:
        return [
            task
            for task in self.get_tasks()
            if matches_exactly(task.status, status)
        ]

    def get_open_tasks(self) -> list[Task]:
        """Tâches actives et en attente, les urgentes d'abord."""
        return sort_tasks(
            [task for task in self.get_tasks() if task.is_open]
        )

    def get_projects_by_status(
        self,
        status: str,
    ) -> list[Project]:
        return [
            project
            for project in self.get_projects()
            if matches_exactly(project.status, status)
        ]

    # =====================================================
    # Recherche ciblée
    # =====================================================

    def find_project(self, name: str) -> Project | None:
        """Correspondance exacte, sinon partielle si non ambiguë."""
        return _find_one(
            self.get_projects(),
            name,
            lambda project: (project.name, project.filename),
        )

    def find_collaborator(self, name: str) -> Collaborator | None:
        return _find_one(
            self.get_collaborators(),
            name,
            lambda collaborator: (
                collaborator.name,
                collaborator.filename,
            ),
        )

    def find_task(self, name: str) -> Task | None:
        return _find_one(
            self.get_tasks(),
            name,
            lambda task: (task.name,),
        )

    def find_matching_tasks(self, name: str) -> list[Task]:
        """Toutes les tâches correspondant partiellement.

        Sert à afficher les possibilités quand `find_task` est
        bloqué par une ambiguïté.
        """
        return [
            task
            for task in self.get_tasks()
            if contains(task.name, name)
        ]

    def find_matching_projects(self, name: str) -> list[Project]:
        return [
            project
            for project in self.get_projects()
            if contains(project.name, name)
            or contains(project.filename, name)
        ]

    def find_matching_collaborators(
        self,
        name: str,
    ) -> list[Collaborator]:
        return [
            collaborator
            for collaborator in self.get_collaborators()
            if contains(collaborator.name, name)
            or contains(collaborator.filename, name)
        ]

    def find_collaborator_by_discord(
        self,
        discord_username: str,
    ) -> Collaborator | None:
        for collaborator in self.get_collaborators():
            if collaborator.discord is None:
                continue

            if matches_exactly(
                collaborator.discord,
                discord_username,
            ):
                return collaborator

        return None

    def get_tasks_for_project(self, project: Project) -> list[Task]:
        """Tâches rattachées à un projet.

        Le champ `project` des tâches est saisi à la main et ne
        reprend pas forcément le nom du projet. On le confronte
        donc au nom *et* au nom de fichier, après normalisation.
        """
        return sort_tasks(
            [
                task
                for task in self.get_tasks()
                if belongs_to(task, project)
            ]
        )

    def get_notes_for_project(self, project: Project) -> list[Note]:
        """Notes de projet rattachées à un projet.

        Même règle que pour les tâches : le champ `project` est du
        texte libre, saisi depuis un menu dans Obsidian mais libre
        malgré tout. On le confronte au nom du projet *et* à son nom
        de fichier, après normalisation.
        """
        return sorted(
            [
                note
                for note in self.get_notes()
                if belongs_to(note, project)
            ],
            key=lambda note: note.name.casefold(),
        )

    # =====================================================
    # Vue d'ensemble
    # =====================================================

    def workspace(self) -> Workspace:
        """Tous les compteurs du Vault, en un seul parcours."""
        contenu = self._collect_all()

        return Workspace(
            projects=count_projects(contenu.projects),
            tasks=count_tasks(contenu.tasks),
            urgent=sort_tasks(
                [
                    task
                    for task in contenu.tasks
                    if is_urgent(task)
                ]
            ),
            collaborators=count_collaborators(
                contenu.collaborators
            ),
            all_projects=contenu.projects,
            all_tasks=contenu.tasks,
            all_collaborators=contenu.collaborators,
        )

    # =====================================================
    # Recherche transversale
    # =====================================================

    def search(self, query: str) -> SearchResults:
        results = SearchResults(query=query)

        contenu = self._collect_all()

        projects = contenu.projects
        tasks = contenu.tasks
        collaborators = contenu.collaborators

        for project in projects:
            if any(
                contains(value, query)
                for value in (
                    project.name,
                    project.filename,
                    project.category,
                    project.status,
                )
            ):
                results.projects.append(project)

        for collaborator in collaborators:
            if any(
                contains(value, query)
                for value in (
                    collaborator.name,
                    collaborator.filename,
                    collaborator.role,
                    collaborator.company,
                    collaborator.discord,
                    collaborator.github,
                )
            ):
                results.collaborators.append(collaborator)

        for task in tasks:
            if any(
                contains(value, query)
                for value in (
                    task.name,
                    task.project,
                    task.platform,
                    task.collaborator,
                    task.status,
                    task.priority,
                )
            ):
                results.tasks.append(task)

        for note in contenu.knowledge:
            valeurs = (
                note.name,
                note.categorie,
                note.domaine,
                note.sujet,
                note.maturite,
                *note.tags,
            )

            if any(contains(valeur, query) for valeur in valeurs):
                results.knowledge.append(note)

        for note in contenu.notes:
            if any(
                contains(valeur, query)
                for valeur in (note.name, note.sujet, note.project)
            ):
                results.notes.append(note)

        results.tasks = sort_tasks(results.tasks)

        return results


# =====================================================
# Tri et correspondance
# =====================================================

PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def priority_rank(priority: str | None) -> int:
    """Range une priorité inconnue après les priorités connues."""
    if priority is None:
        return len(PRIORITY_ORDER)

    return PRIORITY_ORDER.get(
        priority.casefold(),
        len(PRIORITY_ORDER),
    )


def sort_tasks(tasks: list[Task]) -> list[Task]:
    """Trie par priorité décroissante, puis par échéance.

    Les tâches sans échéance exploitable (le Vault contient des
    `due: x`) passent en dernier.
    """

    def key(task: Task):
        due = task.due or ""
        has_due = bool(due) and due[:4].isdigit()

        return (
            priority_rank(task.priority),
            not has_due,
            due if has_due else "",
            task.name.casefold(),
        )

    return sorted(tasks, key=key)


def same_reference(value: str | None, label: str | None) -> bool:
    """Deux libellés désignent-ils la même chose ?

    Égalité après normalisation, ou inclusion de l'un dans
    l'autre — le Vault utilise les deux formes.
    """
    if not value or not label:
        return False

    return (
        matches_exactly(value, label)
        or contains(value, label)
        or contains(label, value)
    )


# Conservé sous son ancien nom privé : le module l'utilisait ainsi
# avant que les statistiques n'aient besoin de la même règle.
_same_reference = same_reference


def belongs_to(fiche: Task | Note, project: Project) -> bool:
    """Cette note est-elle rattachée à ce projet ?

    Règle unique, partagée par le Repository, les statistiques et
    les notes de projet : le champ `project` est du texte libre, il
    faut le confronter au nom du projet *et* à son nom de fichier.

    Les tâches et les notes de `07-Notes/` portent le même champ et
    obéissent donc à la même règle — c'est ce qui rapproche « DB
    templates web » de `DB_templates-web.md`, quel que soit le type
    de la note qui le cite.
    """
    return any(
        same_reference(fiche.project, label)
        for label in (project.name, project.filename)
    )


def group_tasks_by_project(
    projects: list[Project],
    tasks: list[Task],
) -> dict[str, list[Task]]:
    """Répartit les tâches entre les projets, par nom de projet.

    Une tâche rattachée à aucun projet connu n'apparaît nulle part :
    c'est `orphan_tasks` qui s'en occupe.
    """
    return {
        project.name: sort_tasks(
            [task for task in tasks if belongs_to(task, project)]
        )
        for project in projects
    }


def orphan_tasks(
    projects: list[Project],
    tasks: list[Task],
) -> list[Task]:
    """Tâches qui ne retombent sur aucun projet du Vault."""
    return [
        task
        for task in tasks
        if not any(
            belongs_to(task, project) for project in projects
        )
    ]


def _find_one(items, query, names_getter):
    """Correspondance exacte, sinon partielle si elle est unique.

    Renvoie None en cas d'ambiguïté : mieux vaut ne rien faire que
    d'agir sur la mauvaise note.
    """
    exact = [
        item
        for item in items
        if any(
            matches_exactly(name, query)
            for name in names_getter(item)
        )
    ]

    if exact:
        return exact[0]

    partial = [
        item
        for item in items
        if any(
            contains(name, query) for name in names_getter(item)
        )
    ]

    if len(partial) == 1:
        return partial[0]

    if len(partial) > 1:
        logger.info(
            "Recherche ambiguë (%s) : %d correspondances",
            query,
            len(partial),
        )

    return None
