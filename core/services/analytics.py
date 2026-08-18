"""Lectures transversales du Vault : échéances, activité, santé.

Rien n'est écrit ici, rien n'est affiché ici. Ce module prend des
listes de modèles et rend des chiffres — ce qui le rend testable
sans Vault et sans Discord, et permet aux écrans de n'être que de
la mise en forme.

Un principe traverse le module : **le Vault n'est pas propre**.
Une échéance peut valoir `x`, `X` ou `14j` ; une tâche peut n'avoir
ni projet, ni priorité, ni date. Chaque fonction traite ces cas
comme des informations (« sans échéance ») et jamais comme des
erreurs.
"""

import datetime
from dataclasses import dataclass, field

from core.obsidian.models import Collaborator, Project, Task
from core.obsidian.repository import (
    belongs_to,
    is_urgent,
    sort_tasks,
)


# =====================================================
# Dates
# =====================================================


def parse_date(value: str | None) -> datetime.date | None:
    """Date d'un champ du Vault, ou None s'il n'y en a pas.

    Le Vault contient des valeurs libres (`x`, `X`, `14j`) là où on
    attendrait une date. Elles ne sont pas des erreurs : elles
    signifient « pas d'échéance », et c'est ce que None exprime.
    """
    if not value:
        return None

    texte = str(value).strip()

    if not texte:
        return None

    try:
        return datetime.datetime.fromisoformat(texte).date()
    except ValueError:
        pass

    # `fromisoformat` refuse le « Z » de certains horodatages.
    if texte.endswith("Z"):
        try:
            return datetime.datetime.fromisoformat(
                texte[:-1]
            ).date()
        except ValueError:
            pass

    try:
        return datetime.date.fromisoformat(texte[:10])
    except ValueError:
        return None


def aujourd_hui(now: datetime.datetime | None = None) -> datetime.date:
    if now is None:
        return datetime.date.today()

    return now.date()


# =====================================================
# Progression
# =====================================================


@dataclass(frozen=True)
class Progression:
    """Avancement d'un lot de tâches."""

    termine: int = 0
    total: int = 0

    @property
    def pourcentage(self) -> int:
        if self.total <= 0:
            return 0

        return round(self.termine * 100 / self.total)

    @property
    def restant(self) -> int:
        return max(0, self.total - self.termine)


def progression(tasks: list[Task]) -> Progression:
    """Part des tâches terminées.

    Les tâches **archivées** sont exclues des deux côtés : elles ne
    sont ni faites ni à faire, les compter ferait chuter un
    pourcentage sans que rien n'ait reculé.
    """
    retenues = [
        task
        for task in tasks
        if (task.status or "").casefold() != "archived"
    ]

    termine = sum(
        1
        for task in retenues
        if (task.status or "").casefold() == "completed"
    )

    return Progression(termine=termine, total=len(retenues))


# =====================================================
# Répartitions
# =====================================================

PRIORITES = ("critical", "high", "medium", "low")

PRIORITE_LIBELLES = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

STATUTS = ("active", "waiting", "completed", "archived")

STATUT_LIBELLES = {
    "active": "Active",
    "waiting": "Waiting",
    "completed": "Completed",
    "archived": "Archived",
}


def _compter(valeurs: list[str | None]) -> dict[str, int]:
    compteurs: dict[str, int] = {}

    for valeur in valeurs:
        cle = (valeur or "").casefold()

        compteurs[cle] = compteurs.get(cle, 0) + 1

    return compteurs


def repartition_priorites(
    tasks: list[Task],
) -> list[tuple[str, int]]:
    """Tâches **ouvertes** par priorité, de la plus forte à la plus faible.

    Ouvertes seulement : une répartition qui compte les tâches
    terminées ne dit rien de la charge restante.
    """
    compteurs = _compter(
        [task.priority for task in tasks if task.is_open]
    )

    return [
        (PRIORITE_LIBELLES[cle], compteurs.get(cle, 0))
        for cle in PRIORITES
    ]


def repartition_statuts(tasks: list[Task]) -> list[tuple[str, int]]:
    compteurs = _compter([task.status for task in tasks])

    return [
        (STATUT_LIBELLES[cle], compteurs.get(cle, 0))
        for cle in STATUTS
    ]


def repartition_plateformes(
    tasks: list[Task],
) -> list[tuple[str, int]]:
    """Tâches ouvertes par plateforme, les plus chargées d'abord.

    La plateforme est du texte libre dans le Vault : on affiche ce
    qui s'y trouve plutôt qu'une liste figée, sinon une valeur
    saisie à la main disparaîtrait du décompte.
    """
    compteurs: dict[str, int] = {}

    for task in tasks:
        if not task.is_open:
            continue

        nom = (task.platform or "").strip() or "Non définie"

        compteurs[nom] = compteurs.get(nom, 0) + 1

    return sorted(
        compteurs.items(),
        key=lambda entree: (-entree[1], entree[0].casefold()),
    )


def charge_par_projet(
    projects: list[Project],
    tasks: list[Task],
) -> list[tuple[str, int]]:
    """Nombre de tâches ouvertes par projet, les plus chargés d'abord.

    Les projets sans tâche ouverte sont conservés avec 0 : c'est
    précisément l'information que cherche la vue « projets sans
    activité ».
    """
    ouvertes = [task for task in tasks if task.is_open]

    charges = [
        (
            project.name,
            sum(
                1
                for task in ouvertes
                if belongs_to(task, project)
            ),
        )
        for project in projects
    ]

    return sorted(
        charges,
        key=lambda entree: (-entree[1], entree[0].casefold()),
    )


# =====================================================
# Échéances
# =====================================================


@dataclass(frozen=True)
class Echeances:
    """Tâches ouvertes rangées par urgence de leur échéance."""

    en_retard: list[Task] = field(default_factory=list)
    aujourdhui: list[Task] = field(default_factory=list)
    deux_jours: list[Task] = field(default_factory=list)
    sept_jours: list[Task] = field(default_factory=list)
    plus_tard: list[Task] = field(default_factory=list)
    sans_echeance: list[Task] = field(default_factory=list)

    @property
    def pressantes(self) -> list[Task]:
        """Ce qui exige une décision aujourd'hui."""
        return self.en_retard + self.aujourdhui

    def compteurs(self) -> list[tuple[str, int]]:
        """Pour un histogramme : libellé lisible et effectif."""
        return [
            ("En retard", len(self.en_retard)),
            ("Aujourd'hui", len(self.aujourdhui)),
            ("48 heures", len(self.deux_jours)),
            ("7 jours", len(self.sept_jours)),
            ("Plus tard", len(self.plus_tard)),
            ("Sans date", len(self.sans_echeance)),
        ]


def echeances(
    tasks: list[Task],
    now: datetime.datetime | None = None,
) -> Echeances:
    """Range les tâches ouvertes par proximité d'échéance."""
    jour = aujourd_hui(now)

    groupes: dict[str, list[Task]] = {
        "en_retard": [],
        "aujourdhui": [],
        "deux_jours": [],
        "sept_jours": [],
        "plus_tard": [],
        "sans_echeance": [],
    }

    for task in sort_tasks([t for t in tasks if t.is_open]):
        date = parse_date(task.due)

        if date is None:
            groupes["sans_echeance"].append(task)
            continue

        ecart = (date - jour).days

        if ecart < 0:
            groupes["en_retard"].append(task)
        elif ecart == 0:
            groupes["aujourdhui"].append(task)
        elif ecart <= 2:
            groupes["deux_jours"].append(task)
        elif ecart <= 7:
            groupes["sept_jours"].append(task)
        else:
            groupes["plus_tard"].append(task)

    return Echeances(**groupes)


# =====================================================
# Vue « Aujourd'hui »
# =====================================================


@dataclass(frozen=True)
class Journee:
    """Ce que la journée contient, en quatre listes courtes."""

    urgent: list[Task] = field(default_factory=list)
    a_faire: list[Task] = field(default_factory=list)
    en_attente: list[Task] = field(default_factory=list)
    termine: list[Task] = field(default_factory=list)

    @property
    def vide(self) -> bool:
        return not (
            self.urgent
            or self.a_faire
            or self.en_attente
            or self.termine
        )


def journee(
    tasks: list[Task],
    now: datetime.datetime | None = None,
) -> Journee:
    """Les tâches du jour, réparties en quatre intentions.

    « Urgent » réunit deux choses différentes qui appellent la même
    réaction : ce qui est de priorité haute ou critique, et ce dont
    l'échéance est passée ou tombe aujourd'hui. Une tâche basse
    dont la deadline est dépassée est urgente, quoi qu'en dise sa
    priorité.
    """
    jour = aujourd_hui(now)

    dates = echeances(tasks, now)

    pressantes = {task.path for task in dates.pressantes}

    urgent = []
    a_faire = []
    en_attente = []

    for task in sort_tasks([t for t in tasks if t.is_open]):
        if (task.status or "").casefold() == "waiting":
            en_attente.append(task)
            continue

        if is_urgent(task) or task.path in pressantes:
            urgent.append(task)
            continue

        a_faire.append(task)

    termine = [
        task
        for task in tasks
        if (task.status or "").casefold() == "completed"
        and parse_date(task.completed) == jour
    ]

    return Journee(
        urgent=urgent,
        a_faire=a_faire,
        en_attente=en_attente,
        termine=sorted(termine, key=lambda t: t.name.casefold()),
    )


# =====================================================
# Activité
# =====================================================


def activite(
    tasks: list[Task],
    now: datetime.datetime | None = None,
    jours: int = 7,
) -> list[tuple[datetime.date, int]]:
    """Nombre de mouvements par jour, du plus ancien au plus récent.

    Un « mouvement » est une tâche créée ou terminée. C'est la seule
    activité que le Vault date : rien n'y horodate une lecture ou
    une modification de champ, et inventer une mesure plus fine
    demanderait un journal séparé.
    """
    jour = aujourd_hui(now)

    fenetre = [
        jour - datetime.timedelta(days=decalage)
        for decalage in range(jours - 1, -1, -1)
    ]

    compteurs = {date: 0 for date in fenetre}

    for task in tasks:
        for champ in (task.created, task.completed):
            date = parse_date(champ)

            if date in compteurs:
                compteurs[date] += 1

    return [(date, compteurs[date]) for date in fenetre]


JOURS_COURTS = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


def activite_par_jour(
    tasks: list[Task],
    now: datetime.datetime | None = None,
    jours: int = 7,
) -> list[tuple[str, int]]:
    """Même mesure, libellée par jour de la semaine."""
    return [
        (JOURS_COURTS[date.weekday()], valeur)
        for date, valeur in activite(tasks, now, jours)
    ]


def heatmap(
    tasks: list[Task],
    now: datetime.datetime | None = None,
    semaines: int = 3,
) -> list[list[int]]:
    """Activité en lignes de sept jours, façon GitHub.

    La dernière ligne se termine aujourd'hui : on lit la grille de
    haut en bas comme un calendrier qui remonte le temps.
    """
    valeurs = [
        compte
        for _, compte in activite(tasks, now, jours=semaines * 7)
    ]

    return [
        valeurs[index : index + 7]
        for index in range(0, len(valeurs), 7)
    ]


# =====================================================
# Santé du workspace
# =====================================================

BON = "bon"
ATTENTION = "attention"
CRITIQUE = "critique"

# Ordre de gravité, pour trier et pour choisir la couleur globale.
GRAVITE = {BON: 0, ATTENTION: 1, CRITIQUE: 2}


@dataclass(frozen=True)
class Indicateur:
    domaine: str
    niveau: str
    detail: str


def projets_sans_tache(
    projects: list[Project],
    tasks: list[Task],
) -> list[Project]:
    """Projets actifs qui n'ont aucune tâche ouverte.

    Un projet dans cet état n'est pas forcément malade : il peut
    venir d'être créé. Mais c'est toujours une question à se poser,
    d'où sa présence dans la santé comme dans le nettoyage.
    """
    ouvertes = [task for task in tasks if task.is_open]

    return [
        project
        for project in projects
        if (project.status or "").casefold() == "active"
        and not any(
            belongs_to(task, project) for task in ouvertes
        )
    ]


def sante(
    projects: list[Project],
    tasks: list[Task],
    collaborators: list[Collaborator],
    now: datetime.datetime | None = None,
) -> list[Indicateur]:
    """Quatre indicateurs, un par domaine.

    Les seuils sont volontairement bas : ce tableau sert à un
    workspace personnel, où trois tâches critiques simultanées sont
    déjà de trop.
    """
    dates = echeances(tasks, now)

    ouvertes = [task for task in tasks if task.is_open]

    critiques = [
        task
        for task in ouvertes
        if (task.priority or "").casefold() == "critical"
    ]

    en_attente = [
        task
        for task in ouvertes
        if (task.status or "").casefold() == "waiting"
    ]

    sans_tache = projets_sans_tache(projects, tasks)

    collabs_attente = [
        collaborator
        for collaborator in collaborators
        if (collaborator.status or "").casefold() == "waiting"
    ]

    indicateurs = []

    # --- Projets ---
    if sans_tache:
        indicateurs.append(
            Indicateur(
                "Projets",
                ATTENTION,
                f"{len(sans_tache)} projet(s) actif(s) sans tâche "
                "ouverte",
            )
        )
    else:
        actifs = sum(
            1
            for project in projects
            if (project.status or "").casefold() == "active"
        )

        indicateurs.append(
            Indicateur(
                "Projets",
                BON,
                f"{actifs} projet(s) actif(s), tous suivis",
            )
        )

    # --- Tâches ---
    if len(critiques) > 5:
        indicateurs.append(
            Indicateur(
                "Tâches",
                CRITIQUE,
                f"{len(critiques)} tâches critiques ouvertes",
            )
        )
    elif len(critiques) > 2:
        indicateurs.append(
            Indicateur(
                "Tâches",
                ATTENTION,
                f"{len(critiques)} tâches critiques ouvertes",
            )
        )
    elif en_attente and len(en_attente) * 2 > len(ouvertes):
        indicateurs.append(
            Indicateur(
                "Tâches",
                ATTENTION,
                "plus de la moitié des tâches ouvertes attendent "
                "quelque chose",
            )
        )
    else:
        indicateurs.append(
            Indicateur(
                "Tâches",
                BON,
                f"{len(ouvertes)} tâche(s) ouverte(s), "
                f"{len(critiques)} critique(s)",
            )
        )

    # --- Deadlines ---
    if dates.en_retard:
        indicateurs.append(
            Indicateur(
                "Deadlines",
                CRITIQUE,
                f"{len(dates.en_retard)} échéance(s) dépassée(s)",
            )
        )
    elif dates.aujourdhui:
        indicateurs.append(
            Indicateur(
                "Deadlines",
                ATTENTION,
                f"{len(dates.aujourdhui)} échéance(s) aujourd'hui",
            )
        )
    else:
        indicateurs.append(
            Indicateur(
                "Deadlines",
                BON,
                "aucune échéance dépassée",
            )
        )

    # --- Collaborateurs ---
    if collabs_attente:
        indicateurs.append(
            Indicateur(
                "Collaborateurs",
                ATTENTION,
                f"{len(collabs_attente)} en attente de réponse",
            )
        )
    else:
        actifs = sum(
            1
            for collaborator in collaborators
            if (collaborator.status or "").casefold() == "active"
        )

        indicateurs.append(
            Indicateur(
                "Collaborateurs",
                BON,
                f"{actifs} collaborateur(s) actif(s)",
            )
        )

    return indicateurs


def niveau_global(indicateurs: list[Indicateur]) -> str:
    """Le pire des indicateurs : c'est lui qui donne le ton."""
    if not indicateurs:
        return BON

    return max(
        (indicateur.niveau for indicateur in indicateurs),
        key=lambda niveau: GRAVITE.get(niveau, 0),
    )


# =====================================================
# Détection des incohérences
# =====================================================


@dataclass(frozen=True)
class Probleme:
    """Une incohérence détectée, et de quoi la corriger."""

    cle: str
    titre: str
    conseil: str
    elements: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.elements)


def problemes(
    projects: list[Project],
    tasks: list[Task],
    collaborators: list[Collaborator],
    now: datetime.datetime | None = None,
) -> list[Probleme]:
    """Ce qui empêche le Vault d'être exploitable, du pire au moindre.

    Chaque entrée porte un conseil : une liste de défauts sans
    indication de correction se contente de culpabiliser.

    Seuls les problèmes **présents** sont renvoyés — un Vault propre
    doit produire une liste vide, pas une page de zéros.
    """
    ouvertes = [task for task in tasks if task.is_open]

    dates = echeances(tasks, now)

    candidats = [
        Probleme(
            "retard",
            "Tâches en retard",
            "Reporter l'échéance ou terminer la tâche.",
            [task.name for task in dates.en_retard],
        ),
        Probleme(
            "inbox",
            "Captures à trier",
            "Leur donner un projet et une priorité, puis les "
            "sortir de l'Inbox en changeant leur statut.",
            [task.name for task in ouvertes if task.is_inbox],
        ),
        Probleme(
            "sans_projet",
            "Tâches sans projet",
            "Choisir un projet dans le menu de la tâche.",
            [
                task.name
                for task in ouvertes
                if not (task.project or "").strip()
            ],
        ),
        Probleme(
            "sans_priorite",
            "Tâches sans priorité",
            "Sans priorité, une tâche n'apparaît jamais en tête "
            "de liste.",
            [
                task.name
                for task in ouvertes
                if (task.priority or "").casefold()
                not in PRIORITES
            ],
        ),
        Probleme(
            "sans_echeance",
            "Tâches sans échéance",
            "Le menu Délai en pose une en un clic.",
            [task.name for task in dates.sans_echeance],
        ),
        Probleme(
            "projets_sans_tache",
            "Projets actifs sans tâche",
            "Un projet actif sans tâche ouverte est soit terminé, "
            "soit en attente de sa première tâche.",
            [
                project.name
                for project in projets_sans_tache(projects, tasks)
            ],
        ),
        Probleme(
            "collabs_sans_discord",
            "Collaborateurs sans pseudo Discord",
            "Sans pseudo, impossible de les retrouver par leur "
            "identifiant Discord.",
            [
                collaborator.name
                for collaborator in collaborators
                if (collaborator.status or "").casefold()
                != "completed"
                and not (collaborator.discord or "").strip()
            ],
        ),
    ]

    return [probleme for probleme in candidats if probleme.elements]
