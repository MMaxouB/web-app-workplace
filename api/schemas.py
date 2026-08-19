"""Conversion des modèles du Vault en objets JSON.

Les dataclasses de `core.obsidian.models` portent des `Path`, que
JSON ne sait pas représenter. Chaque note reçoit donc un identifiant
stable dérivé de son chemin relatif au Vault (§26 : « les
identifiants doivent permettre de retrouver le fichier Markdown
correspondant »).

L'encodage est du base64 URL-safe : le Vault contient des accents,
des espaces et des caractères comme « + », qui traversent mal une
URL. Le décodage refait le chemin exact, et `_check_path` du Vault
reste le garde-fou en cas d'identifiant forgé.
"""

import base64
from pathlib import Path

from core.obsidian.models import (
    Collaborator,
    Knowledge,
    Note,
    Project,
    Task,
)
from core.services import analytics, connaissances
from core.utils.markdown import Case


def encode_id(path: Path, vault_path: Path) -> str:
    relatif = str(path.resolve().relative_to(vault_path))

    return base64.urlsafe_b64encode(
        relatif.encode("utf-8")
    ).decode("ascii").rstrip("=")


def decode_id(note_id: str, vault_path: Path) -> Path:
    """Refait le chemin d'une note à partir de son identifiant.

    Lève ValueError si l'identifiant n'est pas décodable. Le chemin
    obtenu n'est pas réputé sûr pour autant : c'est `_check_path`
    du Vault qui vérifie qu'il reste à l'intérieur.
    """
    padding = "=" * (-len(note_id) % 4)

    try:
        relatif = base64.urlsafe_b64decode(
            note_id + padding
        ).decode("utf-8")
    except Exception as error:
        raise ValueError(f"Identifiant illisible : {note_id}") from error

    return (vault_path / relatif).resolve()


# =====================================================
# Sérialisation
# =====================================================


def _version(path: Path) -> float | None:
    """Date de modification, servant de numéro de version.

    Portée par chaque tâche listée pour que le kanban et le
    calendrier puissent détecter une modification concurrente sans
    relire la fiche complète avant chaque glisser-déposer.
    """
    try:
        return round(path.stat().st_mtime, 3)
    except OSError:
        return None


def task_to_dict(task: Task, vault_path: Path) -> dict:
    due = analytics.parse_date(task.due)

    return {
        "id": encode_id(task.path, vault_path),
        "version": _version(task.path),
        "name": task.name,
        "status": task.status,
        "priority": task.priority,
        "platform": task.platform,
        "project": task.project,
        "collaborator": task.collaborator,
        "created": task.created,
        "deadline": task.deadline,
        "due": task.due,
        # Date exploitable par le frontend, ou None quand le champ
        # porte une valeur libre (`x`, `14j`) : ce n'est pas une
        # erreur, ça veut dire « pas d'échéance ».
        "due_date": due.isoformat() if due else None,
        "completed": task.completed,
        "is_open": task.is_open,
        "is_inbox": task.is_inbox,
        "folder": task.path.parent.name,
    }


def project_to_dict(project: Project, vault_path: Path) -> dict:
    return {
        "id": encode_id(project.path, vault_path),
        "name": project.name,
        "filename": project.filename,
        "status": project.status,
        "category": project.category,
        "priority": project.priority,
        "created": project.created,
        "deadline": project.deadline,
        "repository": project.repository,
        "folder": project.path.parent.name,
    }


def collaborator_to_dict(
    collaborator: Collaborator,
    vault_path: Path,
) -> dict:
    return {
        "id": encode_id(collaborator.path, vault_path),
        "name": collaborator.name,
        "filename": collaborator.filename,
        "status": collaborator.status,
        "role": collaborator.role,
        "company": collaborator.company,
        "discord": collaborator.discord,
        "email": collaborator.email,
        "github": collaborator.github,
        "website": collaborator.website,
        "timezone": collaborator.timezone,
        "joined": collaborator.joined,
    }


def knowledge_to_dict(
    knowledge: Knowledge,
    vault_path: Path,
) -> dict:
    """Une connaissance, prête pour l'écran.

    `domaine` et `sujet` sont les valeurs **effectives** : celles que
    la note déclare, ou à défaut celles que son dossier indique. La
    navigation s'appuie dessus, et une note au frontmatter incomplet
    doit rester rangée quelque part plutôt que de disparaître.

    `range_correctement` dit si les deux coïncident. C'est le
    contrôle de cohérence des conventions, ramené à l'écran : une
    note qui annonce un domaine et vit dans un autre dossier n'est
    pas cassée, elle est simplement introuvable là où on la
    cherchera.
    """
    return {
        "id": encode_id(knowledge.path, vault_path),
        "version": _version(knowledge.path),
        "name": knowledge.name,
        "categorie": knowledge.categorie,
        "domaine": connaissances.domaine_de(knowledge, vault_path),
        "sujet": connaissances.sujet_de(knowledge, vault_path),
        "domaine_declare": knowledge.domaine,
        "maturite": knowledge.maturite,
        "tags": list(knowledge.tags),
        "source": knowledge.source,
        "created": knowledge.created,
        "mis_a_jour": knowledge.mis_a_jour,
        "dossier": str(knowledge.path.parent.relative_to(vault_path)),
        "range_correctement": connaissances.dossier_coherent(
            knowledge,
            vault_path,
        ),
    }


def note_to_dict(note: Note, vault_path: Path) -> dict:
    return {
        "id": encode_id(note.path, vault_path),
        "version": _version(note.path),
        "name": note.name,
        "project": note.project,
        "sujet": note.sujet,
        "created": note.created,
        "mis_a_jour": note.mis_a_jour,
        "is_archived": note.is_archived,
        "folder": note.path.parent.name,
    }


def case_to_dict(case: Case) -> dict:
    """Un point à cocher.

    `index` est le rang de la case dans la note, et `texte` le
    libellé affiché. Les deux repartent ensemble au serveur quand on
    coche : le rang désigne la ligne, le libellé vérifie qu'elle dit
    toujours la même chose.
    """
    return {
        "index": case.index,
        "texte": case.texte,
        "cochee": case.cochee,
        "niveau": case.niveau,
    }


def progression_to_dict(progression: analytics.Progression) -> dict:
    return {
        "termine": progression.termine,
        "total": progression.total,
        "restant": progression.restant,
        "pourcentage": progression.pourcentage,
    }
