"""Configuration de l'application.

Remplace `bot/config/settings.py`, qui exigeait un token Discord pour
démarrer. Ici, une seule chose est nécessaire : le chemin du Vault.

Il est cherché dans cet ordre :

1. la variable d'environnement `OBSIDIAN_VAULT_PATH` ;
2. un fichier `.env` posé à côté du projet ;
3. le dossier `travail/` voisin, qui est l'emplacement réel.

Le troisième cas évite d'avoir à configurer quoi que ce soit pour
lancer l'application sur cette machine.
"""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Emplacement réel du Vault : voisin du dossier de code.
DEFAULT_VAULT_PATH = PROJECT_ROOT.parent / "travail"


def _read_env_file() -> dict[str, str]:
    """Lit un `.env` minimal, sans dépendance externe.

    Le bot utilisait python-dotenv pour ça. Le besoin se limite à
    quelques lignes `CLE=valeur` : autant ne pas ajouter une
    dépendance pour vingt lignes de code.
    """
    fichier = PROJECT_ROOT / ".env"

    if not fichier.is_file():
        return {}

    valeurs = {}

    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()

        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue

        cle, _, valeur = ligne.partition("=")

        valeurs[cle.strip()] = valeur.strip().strip("\"'")

    return valeurs


def resolve_vault_path() -> Path:
    brut = os.getenv("OBSIDIAN_VAULT_PATH") or _read_env_file().get(
        "OBSIDIAN_VAULT_PATH"
    )

    if brut:
        return Path(brut).expanduser().resolve()

    return DEFAULT_VAULT_PATH.resolve()


VAULT_PATH = resolve_vault_path()

# Interface d'écoute. Volontairement bouclée sur la machine locale :
# le Vault contient des données personnelles et l'API n'a aucune
# authentification. Écouter sur 0.0.0.0 l'exposerait au réseau.
HOST = os.getenv("VAULT_WEB_HOST", "127.0.0.1")

PORT = int(os.getenv("VAULT_WEB_PORT", "8765"))

# Étiquette inscrite dans l'historique des notes modifiées. Le bot
# écrivait « (depuis Discord) » en dur ; c'est désormais un réglage.
SOURCE_LABEL = os.getenv("VAULT_WEB_SOURCE", "depuis la web app")
