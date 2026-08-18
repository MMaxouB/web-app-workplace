"""Fixtures partagées.

Règle absolue : aucun test d'écriture ne touche au vrai Vault.
Tout se passe dans un Vault temporaire construit par pytest, qui
reproduit les particularités réelles du Vault de production
(fichier Templater non-YAML, note sans frontmatter, tâche aux
champs incomplets).
"""

from pathlib import Path

import pytest

from core.obsidian.repository import ObsidianRepository
from core.obsidian.vault import ObsidianVault


TACHE_COMPLETE = """---
type: task
status: active
priority: critical
platform: "Code"
project: "Projet Alpha"
collaborator: "Moi"
created: 2026-08-13T23:04:57+02:00
deadline: "14j"
due: 2026-08-27T23:04:57+02:00
completed:
---

# Tache complete

## Informations

| Propriété     | Valeur                    |
| ------------- | ------------------------- |
| Statut        | `active`                  |
| Priorité      | `critical`                |
| Plateforme    | Code                      |
| Projet        | Projet Alpha              |
| Collaborateur | Moi                       |
| Créée le      | 13/08/2026 23:04          |
| Délai         | 14j                       |
| Deadline      | 27/08/2026 23:04          |

## Objectif

Faire quelque chose.

## Checklist

- [ ]

## Notes

-

## Historique

### 13/08/2026 23:04

- Tâche créée.
"""

TACHE_ATTENTE = """---
type: task
status: waiting
priority: low
platform: "Autre"
project: "Projet Beta"
collaborator: "Moi"
created: 2026-08-10
due: x
completed:
---

# Tache attente
"""

TACHE_MINIMALE = """---
type: task
---

# Tache minimale

Aucun statut, aucune priorité : le bot ne doit pas planter.
"""

# Nom accentué, comme « Créer bot discord + serv.md » dans le
# vrai Vault : la recherche doit fonctionner sans les accents.
TACHE_ACCENTUEE = """---
type: task
status: active
priority: high
platform: "Discord"
project: "Projet Alpha"
collaborator: "Moi"
created: 2026-08-12
due: 2026-08-25
completed:
---

# Créer bot Discord
"""

TACHE_TERMINEE = """---
type: task
status: completed
priority: medium
platform: "Obsidian"
project: "Projet Beta"
collaborator: "Moi"
created: 2026-08-01
due: 2026-08-05
completed: 2026-08-05
---

# Tache terminee
"""

PROJET = """---
type: project
status: active
name: Projet Alpha
category: software
priority: high
created: 2026-08-01
deadline: X
repository: https://example.invalid/alpha
---

# Projet Alpha

## Informations

| Champ     | Information |
| --------- | ----------- |
| Statut    | Actif       |
| Priorité  | High        |
| Catégorie | Software    |
| Création  | 2026-08-01  |
| Deadline  | —           |

## Description

Un projet de test.

## Collaborateurs

- [[Alice]] — Développement

## Notes

...

## Historique

### 2026-08-01
- Projet créé.
"""

COLLABORATEUR = """---
type: collaborator
status: active
name: Alice
role: Developpeuse
company:
discord: alice#0001
email:
github: alice
website:
timezone: Europe/Paris
joined: 2026-08-05
---

# Alice

## Informations

| Champ          | Information |
| -------------- | ----------- |
| Nom            | Alice       |
| Rôle           | Developpeuse |
| Statut         | active      |
| Entreprise     |             |
| Fuseau horaire | Europe/Paris |

## Contacts

| Plateforme | Contact    |
| ---------- | ---------- |
| Discord    | alice#0001 |
| Email      |            |
| GitHub     | alice      |
| Website    |            |

## Projets

- [[Projet Alpha]]

## Notes

-

## Historique

### 2026-08-05
- Fiche créée.
"""

# Reproduit 99-Templates/template-taches.md : du code Templater,
# que PyYAML ne sait pas lire.
TEMPLATE_TEMPLATER = """---
<%*
let status = await tp.system.suggester(
    ["Active", "En attente"],
    ["active", "waiting"]
);
%>
type: task
status: <% status %>
---

# <% tp.file.title %>
"""

SANS_FRONTMATTER = """# Note libre

Ce fichier n'a pas de frontmatter, comme 02-Projects/Projects.md.
"""


@pytest.fixture
def temp_vault_path(tmp_path: Path) -> Path:
    """Construit un Vault temporaire calqué sur le vrai."""
    files = {
        "05-Tasks/Actives/Tache complete.md": TACHE_COMPLETE,
        "05-Tasks/Actives/Créer bot Discord.md": TACHE_ACCENTUEE,
        "05-Tasks/En attente/Tache attente.md": TACHE_ATTENTE,
        "05-Tasks/_Inbox/Tache minimale.md": TACHE_MINIMALE,
        "05-Tasks/Terminées/Tache terminee.md": TACHE_TERMINEE,
        "02-Projects/Actifs/Projet Alpha.md": PROJET,
        "02-Projects/Projects.md": SANS_FRONTMATTER,
        "01-Collaborateurs/Actifs/Alice.md": COLLABORATEUR,
        "99-Templates/template-taches.md": TEMPLATE_TEMPLATER,
    }

    for relative_path, content in files.items():
        file_path = tmp_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    for empty_folder in (
        "05-Tasks/Terminées",
        "05-Tasks/Archives",
        "02-Projects/En attente",
        "02-Projects/Terminés",
        "02-Projects/Archives",
        "01-Collaborateurs/En attente",
        "01-Collaborateurs/Terminés",
    ):
        (tmp_path / empty_folder).mkdir(
            parents=True,
            exist_ok=True,
        )

    return tmp_path


@pytest.fixture
def temp_vault(temp_vault_path: Path) -> ObsidianVault:
    return ObsidianVault(temp_vault_path)


@pytest.fixture
def temp_repository(
    temp_vault: ObsidianVault,
) -> ObsidianRepository:
    return ObsidianRepository(temp_vault)
