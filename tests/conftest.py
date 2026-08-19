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

# =====================================================
# Connaissances, notes de projet et journal
# =====================================================

CONNAISSANCE_TECHNIQUE = """---
type: knowledge
categorie: technique
domaine: Cybersecurity
sujet: Web
maturite: stable
tags: [xss, dom, bypass, web]
source: https://example.invalid/xss
created: 2026-08-18
mis_a_jour: 2026-08-18
---

# XSS stockee

## En bref

Le script est enregistre cote serveur et rejoue a chaque visite.

## Pieges

Un filtre cote navigateur ne protege de rien.

## Voir aussi

- [[ffuf]]
"""

CONNAISSANCE_OUTIL = """---
type: knowledge
categorie: outil
domaine: Outils
sujet: Offensifs
maturite: brouillon
tags: [fuzzing, web]
source:
created: 2026-08-18
mis_a_jour: 2026-08-19
---

# ffuf

## En bref

Fuzzer HTTP rapide.

## Voir aussi

- [[XSS stockee]]
- [[Note qui n existe pas]]
"""

# Le `domaine:` ne correspond pas au dossier : c'est le cas que la
# requête de contrôle des conventions cherche à faire apparaître.
CONNAISSANCE_MAL_RANGEE = """---
type: knowledge
categorie: concept
domaine: Cybersecurity
maturite: graine
tags:
created: 2026-08-19
mis_a_jour: 2026-08-19
---

# Modele OSI

Sept couches.
"""

# Ni `domaine:` ni `sujet:` : le dossier doit prendre le relais.
CONNAISSANCE_SANS_CHAMPS = """---
type: knowledge
categorie: reference
maturite: stable
---

# Ports courants

| Port | Service |
|---|---|
| 22 | SSH |
"""

NOTE_DE_PROJET = """---
type: note
project: "Projet Alpha"
sujet: points a verifier
created: 2026-08-18
mis_a_jour: 2026-08-18
---

# Points Alpha

## Points

- [ ] verifier le rendu
- [x] relire le texte
  - [ ] sous-point indente

## Notes

- le client prefere la version sombre

## Voir aussi

- [[XSS stockee]]
"""

NOTE_SANS_PROJET = """---
type: note
project:
sujet: idees
created: 2026-08-19
mis_a_jour: 2026-08-19
---

# Idees en vrac

## Points

- [ ] tester autre chose
"""

NOTE_ARCHIVEE = """---
type: note
project: "Projet Alpha"
sujet: terminee
created: 2026-08-01
mis_a_jour: 2026-08-02
---

# Ancienne note

## Points

- [x] plus rien a faire
"""

# Reproduit 07-Notes/Journal.md : un préambule, une règle
# horizontale, puis une section par jour du plus ancien au plus
# récent — avec la puce vide que dépose le gabarit.
JOURNAL = """---
type: journal
sujet: Capture rapide
created: 2026-08-18
---

# Journal

Ce qu'on note quand on n'a pas le temps de decider ou le ranger.

---

## 2026-08-18

- rappeler le client
- verifier postgres

## 2026-08-19

- 
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
        "06-Connaissances/Cybersecurity/Web/XSS stockee.md": (
            CONNAISSANCE_TECHNIQUE
        ),
        "06-Connaissances/Outils/Offensifs/ffuf.md": CONNAISSANCE_OUTIL,
        "06-Connaissances/Concepts/Modele OSI.md": (
            CONNAISSANCE_MAL_RANGEE
        ),
        "06-Connaissances/References/Ports courants.md": (
            CONNAISSANCE_SANS_CHAMPS
        ),
        "07-Notes/Points Alpha.md": NOTE_DE_PROJET,
        "07-Notes/Idees en vrac.md": NOTE_SANS_PROJET,
        "07-Notes/Archives/Ancienne note.md": NOTE_ARCHIVEE,
        "07-Notes/Journal.md": JOURNAL,
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
