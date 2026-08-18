"""Comparaison de texte tolérante.

Le Vault est en français : les noms contiennent des accents, des
majuscules et de la ponctuation. Taper « creer bot » depuis
Discord doit retrouver « Créer bot discord + serv ».
"""

import unicodedata


def normalize(value: str | None) -> str:
    """Minuscules, sans accents, sans ponctuation.

    La ponctuation devient de l'espace pour que les variations de
    saisie du Vault se rejoignent. Le champ `project` des tâches
    est libre et ne reprend pas le nom exact du projet :

        « AI-powered video editor »  (tâche)
        « AI-Powered Video Editor »  (fichier du projet)
        « DB templates web »         (tâche)
        « DB_templates-web »         (fichier du projet)

    Les deux paires deviennent identiques après normalisation.
    """
    if not value:
        return ""

    decomposed = unicodedata.normalize("NFKD", value)

    cleaned = "".join(
        char if char.isalnum() else " "
        for char in decomposed
        if not unicodedata.combining(char)
    )

    return " ".join(cleaned.casefold().split())


def matches_exactly(value: str | None, query: str) -> bool:
    return normalize(value) == normalize(query)


def contains(value: str | None, query: str) -> bool:
    normalized_query = normalize(query)

    if not normalized_query:
        return False

    return normalized_query in normalize(value)
