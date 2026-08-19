"""Écriture sécurisée dans le Vault.

Principe directeur : le Vault prime sur le bot. Toute écriture
passe par ce module, qui garantit six choses.

1. Le fichier visé est bien dans le Vault, et c'est du Markdown.
2. Son contenu actuel est lu et gardé en mémoire avant tout.
3. Seule la partie nécessaire est modifiée — jamais de
   reconstruction du fichier.
4. L'écriture est atomique : fichier temporaire puis remplacement.
5. Le résultat est relu et validé.
6. En cas de résultat invalide, le contenu d'origine est restauré.

Le frontmatter n'est JAMAIS régénéré par PyYAML : un aller-retour
`safe_load` / `safe_dump` réécrit 7 lignes sur 10 sur les tâches
réelles (guillemets perdus, `completed:` transformé en
`completed: null`, et surtout `due: 2026-08-27T23:04:57+02:00`
transformé en `due: 2026-08-27 23:04:57+02:00`, ce qui casserait
le dashboard Obsidian). On édite donc ligne par ligne.
"""

import logging
import os
import shutil
from pathlib import Path

import yaml

from core.obsidian.vault import ObsidianVault
from core.utils.markdown import ecrire_case, lire_cases
from core.utils.text import normalize


logger = logging.getLogger(__name__)


# Caractères qui obligent à mettre une valeur entre guillemets.
_NEEDS_QUOTES = set(":#{}[]&*!|>'\"%@`,")


class VaultWriteError(Exception):
    """Écriture refusée ou annulée."""


def flatten(value: str) -> str:
    """Ramène une valeur sur une seule ligne.

    Sans cela, un message Discord multi-ligne injecterait des clés
    dans le frontmatter :

        !task set project "X" = foo
        status: archived

    aurait écrit une ligne « status: archived » supplémentaire.
    Les caractères de contrôle sont retirés pour la même raison.
    """
    cleaned = "".join(
        " " if character in "\r\n\t" else character
        for character in value
        if character in "\r\n\t" or ord(character) >= 32
    )

    return " ".join(cleaned.split())


def format_value(value: str | None) -> str:
    """Met en forme une valeur de frontmatter.

    Reproduit le style de Templater : les valeurs simples sont
    nues, les autres sont entre guillemets doubles.
    """
    if value is None or value == "":
        return ""

    value = flatten(str(value))

    if not value:
        return ""

    needs_quotes = (
        any(char in _NEEDS_QUOTES for char in value)
        or value != value.strip()
        or value.casefold()
        in ("true", "false", "null", "yes", "no", "on", "off")
    )

    if needs_quotes:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')

        return f'"{escaped}"'

    return value


class VaultWriter:
    def __init__(self, vault: ObsidianVault):
        self.vault = vault

    # =====================================================
    # Primitives protégées
    # =====================================================

    def _check_writable(self, file_path: Path) -> Path:
        """Valide la cible d'une écriture."""
        file_path = self.vault._check_path(file_path)

        if not file_path.is_file():
            raise VaultWriteError(
                f"Le fichier n'existe pas : {file_path}"
            )

        return file_path

    def _atomic_write(self, file_path: Path, content: str) -> None:
        """Écrit via un fichier temporaire puis remplacement.

        Un plantage en cours d'écriture ne peut pas laisser une
        note à moitié écrite. Le temporaire est caché et ne se
        termine pas par « .md » : Obsidian l'ignore.
        """
        temporary = file_path.parent / f".{file_path.name}.tmp"

        try:
            temporary.write_text(content, encoding="utf-8")

            os.replace(temporary, file_path)
        finally:
            if temporary.exists():
                temporary.unlink()

        rendre_visible(file_path)

    def _write_and_validate(
        self,
        file_path: Path,
        new_content: str,
        original_content: str,
        *,
        expect_frontmatter: bool = True,
        verify=None,
    ) -> None:
        """Écrit, relit, valide, et restaure en cas de problème.

        `verify` reçoit le frontmatter relu et doit lever si le
        résultat ne correspond pas à l'intention. Il s'exécute
        DANS la zone protégée : un échec restaure le fichier.
        """
        self._atomic_write(file_path, new_content)

        try:
            if not file_path.is_file():
                raise VaultWriteError(
                    "Le fichier a disparu après écriture."
                )

            data = {}

            if expect_frontmatter:
                data = self.vault.read_frontmatter(file_path)

                if not data:
                    raise VaultWriteError(
                        "Le frontmatter est vide après écriture."
                    )

            if verify is not None:
                verify(data)
        except Exception as error:
            logger.error(
                "Écriture annulée sur %s : %s — restauration.",
                file_path,
                error,
            )

            self._atomic_write(file_path, original_content)

            raise VaultWriteError(
                f"Écriture annulée, fichier restauré : {error}"
            ) from error

    # =====================================================
    # Frontmatter
    # =====================================================

    def _locate_frontmatter(
        self,
        lines: list[str],
        file_path: Path,
    ) -> tuple[int, int]:
        """Renvoie les index des délimiteurs « --- »."""
        if not lines or lines[0].strip() != "---":
            raise VaultWriteError(
                f"Le fichier n'a pas de frontmatter : {file_path}"
            )

        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return 0, index

        raise VaultWriteError(
            f"Frontmatter non fermé : {file_path}"
        )

    def set_frontmatter_field(
        self,
        file_path: Path,
        key: str,
        value: str | None,
    ) -> None:
        """Modifie une seule ligne du frontmatter.

        Le reste du fichier est conservé à l'identique, y compris
        les fins de ligne et le corps du document.
        """
        self.set_frontmatter_fields(file_path, {key: value})

    def set_frontmatter_fields(
        self,
        file_path: Path,
        fields: dict[str, str | None],
    ) -> None:
        """Modifie plusieurs lignes du frontmatter en une écriture.

        Un formulaire web qui change quatre champs déclencherait
        autrement quatre cycles écriture + relecture + `fsync`, et
        autant d'événements pour le surveillant d'Obsidian. Ici, le
        fichier n'est écrit qu'une fois, et la vérification finale
        contrôle *tous* les champs demandés : si l'un d'eux n'est
        pas relu correctement, le fichier d'origine est restauré en
        entier.

        L'ordre des clés du dictionnaire est conservé, et les clés
        absentes du frontmatter sont ajoutées avant sa fermeture.
        """
        if not fields:
            return

        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        lines = original_content.splitlines(keepends=True)

        for key, value in fields.items():
            # Recalculé à chaque tour : une clé ajoutée décale la
            # ligne de fermeture du frontmatter.
            start, end = self._locate_frontmatter(lines, file_path)

            formatted = format_value(value)

            new_line_body = (
                f"{key}: {formatted}" if formatted else f"{key}:"
            )

            target_index = None

            for index in range(start + 1, end):
                stripped = lines[index].lstrip()

                if not stripped.startswith(f"{key}:"):
                    continue

                # Une clé indentée appartient à un bloc parent.
                if lines[index][: len(lines[index]) - len(stripped)]:
                    continue

                target_index = index
                break

            if target_index is None:
                # Clé absente : on l'ajoute juste avant la fermeture.
                lines.insert(end, new_line_body + "\n")

                logger.info(
                    "Champ ajouté au frontmatter : %s -> %r (%s)",
                    key,
                    value,
                    file_path.name,
                )
            else:
                self._refuse_block_value(
                    lines,
                    target_index,
                    end,
                    key,
                )

                ending = _line_ending(lines[target_index])

                lines[target_index] = new_line_body + ending

                logger.info(
                    "Champ modifié : %s -> %r (%s)",
                    key,
                    value,
                    file_path.name,
                )

        def verifier(data: dict) -> None:
            for key, value in fields.items():
                self._assert_field(data, key, value)

        self._write_and_validate(
            file_path,
            "".join(lines),
            original_content,
            verify=verifier,
        )

    def _refuse_block_value(
        self,
        lines: list[str],
        target_index: int,
        end: int,
        key: str,
    ) -> None:
        """Refuse de toucher à une valeur sur plusieurs lignes.

        Remplacer la seule ligne « key: » d'une liste YAML
        laisserait ses éléments orphelins. Ce Vault n'en contient
        pas aujourd'hui, mais le jour où il en aura, mieux vaut
        échouer que corrompre.
        """
        next_index = target_index + 1

        if next_index >= end:
            return

        following = lines[next_index]

        if following.strip() and following[:1] in (" ", "\t", "-"):
            raise VaultWriteError(
                f"Le champ « {key} » a une valeur sur plusieurs "
                "lignes : modification refusée."
            )

    def _assert_field(
        self,
        data: dict,
        key: str,
        value: str | None,
    ) -> None:
        """Vérifie que la relecture donne bien la valeur voulue.

        Exécuté dans la zone protégée de `_write_and_validate` :
        toute anomalie déclenche la restauration du fichier.
        """
        written = data.get(key)

        expected = (
            flatten(str(value)) if value is not None else None
        )

        expected_empty = expected is None or expected == ""

        if expected_empty:
            if written not in (None, ""):
                raise VaultWriteError(
                    f"Le champ « {key} » vaut {written!r} après "
                    "écriture alors qu'il devait être vide."
                )
            return

        if str(written) != expected:
            raise VaultWriteError(
                f"Le champ « {key} » vaut {written!r} après "
                f"écriture au lieu de {expected!r}."
            )

    # =====================================================
    # Fichiers
    # =====================================================

    def create_note(
        self,
        file_path: Path,
        content: str,
    ) -> Path:
        """Crée une note. Refuse d'écraser un fichier existant."""
        file_path = self.vault._check_path(file_path)

        if file_path.exists():
            raise VaultWriteError(
                f"Un fichier porte déjà ce nom : {file_path.name}"
            )

        file_path.parent.mkdir(parents=True, exist_ok=True)

        self._atomic_write(file_path, content)

        try:
            self.vault.read_frontmatter(file_path)
        except ValueError as error:
            file_path.unlink(missing_ok=True)

            raise VaultWriteError(
                f"Note créée invalide, annulation : {error}"
            ) from error

        logger.info("Note créée : %s", file_path)

        return file_path

    def move_note(
        self,
        file_path: Path,
        destination_folder: Path,
    ) -> Path:
        """Déplace une note. Refuse d'écraser la destination."""
        file_path = self._check_writable(file_path)

        destination_folder = destination_folder.resolve()

        if not destination_folder.is_relative_to(self.vault.path):
            raise VaultWriteError(
                "La destination est en dehors du Vault."
            )

        destination = destination_folder / file_path.name

        if destination == file_path:
            logger.info(
                "Déplacement inutile, déjà au bon endroit : %s",
                file_path.name,
            )

            return file_path

        if destination.exists():
            raise VaultWriteError(
                "Un fichier porte déjà ce nom à destination : "
                f"{destination}"
            )

        destination_folder.mkdir(parents=True, exist_ok=True)

        shutil.move(str(file_path), str(destination))

        logger.info(
            "Note déplacée : %s -> %s",
            file_path,
            destination,
        )

        return destination

    # =====================================================
    # Tableau « Informations »
    # =====================================================

    def set_table_field(
        self,
        file_path: Path,
        label: str,
        value: str,
    ) -> bool:
        """Met à jour une ligne du tableau « Informations ».

        Ce tableau recopie le frontmatter à l'usage humain. Il est
        secondaire : si la ligne est absente, on renvoie False
        sans lever, pour ne jamais faire échouer une opération à
        cause d'un élément décoratif.

        L'alignement des colonnes est préservé — Obsidian aligne
        les tableaux, et on ne veut pas les rendre bancals.
        """
        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        lines = original_content.splitlines(keepends=True)

        target_index = None
        cells = None

        for index, line in enumerate(lines):
            if not line.lstrip().startswith("|"):
                continue

            parts = line.split("|")

            if len(parts) < 4:
                continue

            if normalize(parts[1]) == normalize(label):
                target_index = index
                cells = parts
                break

        if target_index is None or cells is None:
            logger.info(
                "Ligne « %s » absente du tableau de %s : ignorée.",
                label,
                file_path.name,
            )

            return False

        original_cell = cells[2]

        # On conserve le style : `valeur` entre accents graves ou non.
        uses_code = original_cell.strip().startswith("`")

        rendered = f"`{value}`" if uses_code else value

        new_cell = f" {rendered} "

        if len(new_cell) < len(original_cell):
            new_cell += " " * (len(original_cell) - len(new_cell))

        cells[2] = new_cell

        lines[target_index] = "|".join(cells)

        self._write_and_validate(
            file_path,
            "".join(lines),
            original_content,
            expect_frontmatter=_has_frontmatter(original_content),
        )

        logger.info(
            "Tableau mis à jour : %s -> %r (%s)",
            label,
            value,
            file_path.name,
        )

        return True

    # =====================================================
    # Corps du document
    # =====================================================

    def add_bullet_under_heading(
        self,
        file_path: Path,
        section: str,
        heading: str,
        bullet: str,
    ) -> None:
        """Ajoute une puce sous un sous-titre daté d'une section.

        Reproduit la façon dont les fiches projet groupent plusieurs
        puces sous une même date :

            ## Historique

            ### 2026-08-14
            - première entrée
            - deuxième entrée

        Si le sous-titre existe déjà, la puce rejoint le groupe.
        Sinon, un nouveau groupe est créé en tête de section.
        """
        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        lines = original_content.splitlines(keepends=True)

        section_index = _find_heading(lines, section)

        if section_index is None:
            raise VaultWriteError(
                f"Section « {section} » introuvable dans "
                f"{file_path.name}."
            )

        section_end = _find_section_end(lines, section_index)

        heading_index = _find_heading(
            lines[section_index + 1 : section_end],
            heading,
        )

        bullet_line = bullet.rstrip("\n") + "\n"

        if heading_index is None:
            insert_index = section_index + 1

            while (
                insert_index < len(lines)
                and not lines[insert_index].strip()
            ):
                insert_index += 1

            lines.insert(
                insert_index,
                f"{heading}\n{bullet_line}\n",
            )
        else:
            absolute = section_index + 1 + heading_index

            insert_index = absolute + 1

            # On se place après la dernière puce du groupe.
            while insert_index < section_end and (
                lines[insert_index].lstrip().startswith("-")
                or not lines[insert_index].strip()
            ):
                if not lines[insert_index].strip():
                    break

                insert_index += 1

            lines.insert(insert_index, bullet_line)

        self._write_and_validate(
            file_path,
            "".join(lines),
            original_content,
            expect_frontmatter=_has_frontmatter(original_content),
        )

        logger.info(
            "Puce ajoutée sous « %s » dans %s",
            heading,
            file_path.name,
        )

    def prepend_to_section(
        self,
        file_path: Path,
        section: str,
        entry: str,
    ) -> None:
        """Insère un bloc en tête d'une section « ## ... ».

        Le Vault range les historiques du plus récent au plus
        ancien : la nouvelle entrée passe donc juste après le
        titre de section. Le reste du fichier n'est pas touché.
        """
        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        lines = original_content.splitlines(keepends=True)

        heading_index = _find_heading(lines, section)

        if heading_index is None:
            raise VaultWriteError(
                f"Section « {section} » introuvable dans "
                f"{file_path.name}."
            )

        insert_index = heading_index + 1

        # On saute les lignes vides qui suivent le titre.
        while (
            insert_index < len(lines)
            and not lines[insert_index].strip()
        ):
            insert_index += 1

        block = entry.rstrip("\n") + "\n\n"

        lines.insert(insert_index, block)

        self._write_and_validate(
            file_path,
            "".join(lines),
            original_content,
            expect_frontmatter=_has_frontmatter(original_content),
        )

        logger.info(
            "Entrée ajoutée dans « %s » de %s",
            section,
            file_path.name,
        )

    def append_bullet_to_section(
        self,
        file_path: Path,
        section: str,
        bullet: str,
    ) -> None:
        """Ajoute une puce **à la fin** d'une section.

        `prepend_to_section` insère en tête, ce qui convient aux
        historiques rangés du plus récent au plus ancien. Le journal
        fait l'inverse : le geste décrit par les conventions est
        « `Ctrl + Fin`, écrire une ligne », donc on écrit à la suite.

        Les emplacements vides laissés par le gabarit du jour — la
        puce « - » que Templater dépose sous chaque nouvelle date —
        sont remplacés plutôt que doublés. Ce n'est pas une ligne du
        journal, c'est un endroit où écrire.
        """
        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        lines = original_content.splitlines(keepends=True)

        heading_index = _find_heading(lines, section)

        if heading_index is None:
            raise VaultWriteError(
                f"Section « {section} » introuvable dans "
                f"{file_path.name}."
            )

        section_end = _find_section_end(lines, heading_index)

        # On recule sur les lignes vides et les puces sans texte qui
        # terminent la section : la nouvelle puce prend leur place.
        fin = section_end

        while fin > heading_index + 1 and _est_un_emplacement_vide(
            lines[fin - 1]
        ):
            fin -= 1

        bloc = [bullet.rstrip("\n") + "\n"]

        if fin == heading_index + 1:
            # Rien entre le titre et la puce : le Vault sépare
            # toujours les deux par une ligne vide.
            bloc.insert(0, "\n")

        if section_end < len(lines):
            # Une section suit : elle a besoin de sa ligne vide.
            bloc.append("\n")

        lines[fin:section_end] = bloc

        self._write_and_validate(
            file_path,
            "".join(lines),
            original_content,
            expect_frontmatter=_has_frontmatter(original_content),
        )

        logger.info(
            "Puce ajoutée en fin de « %s » dans %s",
            section,
            file_path.name,
        )

    def append_block(self, file_path: Path, block: str) -> None:
        """Ajoute un bloc à la fin de la note.

        Sert à ouvrir la section d'un nouveau jour dans le journal :
        les jours s'y empilent du plus ancien au plus récent, pour
        que `Ctrl + Fin` amène directement là où l'on écrit.
        """
        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        nouveau = (
            original_content.rstrip("\n")
            + "\n\n"
            + block.rstrip("\n")
            + "\n"
        )

        self._write_and_validate(
            file_path,
            nouveau,
            original_content,
            expect_frontmatter=_has_frontmatter(original_content),
        )

        logger.info("Bloc ajouté en fin de %s", file_path.name)

    def set_checkbox(
        self,
        file_path: Path,
        index: int,
        cochee: bool,
        texte_attendu: str | None = None,
    ) -> tuple[str, bool]:
        """Coche ou décoche la case de rang `index`.

        Renvoie le libellé de la case et si le fichier a été écrit.

        Une seule ligne change, et d'un seul caractère. Le reste du
        fichier — indentation, texte, fins de ligne — est conservé
        octet pour octet.

        `texte_attendu` est le garde-fou : l'interface envoie le
        libellé qu'elle affichait, et l'écriture est refusée s'il ne
        correspond plus. Sans lui, une note réorganisée dans Obsidian
        entre l'affichage et le clic ferait cocher la mauvaise case —
        et rien ne le signalerait.
        """
        file_path = self._check_writable(file_path)

        original_content = file_path.read_text(encoding="utf-8")

        lines = original_content.splitlines(keepends=True)

        depart = 0

        if _has_frontmatter(original_content):
            _, fermeture = self._locate_frontmatter(lines, file_path)
            depart = fermeture + 1

        cases = lire_cases(original_content, depart=depart)

        if not 0 <= index < len(cases):
            raise VaultWriteError(
                f"La note {file_path.name} n'a pas de case n°"
                f"{index + 1} : elle en compte {len(cases)}."
            )

        case = cases[index]

        if (
            texte_attendu is not None
            and normalize(case.texte) != normalize(texte_attendu)
        ):
            raise VaultWriteError(
                "Cette case ne dit plus la même chose : « "
                f"{case.texte} » au lieu de « {texte_attendu} ». "
                "Recharge la page avant de réessayer."
            )

        if case.cochee == cochee:
            # Rien à écrire : l'état demandé est déjà en place. Un
            # double-clic ne doit pas produire une écriture inutile,
            # ni un événement de plus pour Obsidian.
            return case.texte, False

        lines[case.ligne] = ecrire_case(lines[case.ligne], cochee)

        def verifier(_frontmatter: dict) -> None:
            relues = lire_cases(
                file_path.read_text(encoding="utf-8"),
                depart=depart,
            )

            if len(relues) != len(cases):
                raise VaultWriteError(
                    "Le nombre de cases a changé après écriture."
                )

            if relues[index].cochee is not cochee:
                raise VaultWriteError(
                    f"La case « {case.texte} » n'a pas pris l'état "
                    "demandé."
                )

        self._write_and_validate(
            file_path,
            "".join(lines),
            original_content,
            expect_frontmatter=_has_frontmatter(original_content),
            verify=verifier,
        )

        logger.info(
            "Case %d de %s : %s",
            index + 1,
            file_path.name,
            "cochée" if cochee else "décochée",
        )

        return case.texte, True


# =====================================================
# Utilitaires
# =====================================================


def _est_un_emplacement_vide(line: str) -> bool:
    """Ligne vide, ou puce sans texte laissée par un gabarit."""
    nettoyee = line.strip()

    return nettoyee in ("", "-", "*", "+")


def rendre_visible(file_path: Path) -> bool:
    """Fait voir la note au surveillant de fichiers d'Obsidian.

    Le problème. L'écriture atomique passe par un fichier
    temporaire **caché** — qu'Obsidian ignore, précisément parce
    qu'il commence par un point — puis par un renommage. Obsidian
    ne reçoit donc jamais d'événement d'écriture sur la note
    elle-même. Son index, et avec lui Dataview, peut ignorer
    indéfiniment que le fichier a changé : c'est ce qui laissait
    `05-Tasks/tasks.md` amputé des tâches créées depuis Discord.

    La parade. On rouvre la note et on y réécrit **les mêmes
    octets, sans troncature**. Le système émet alors la séquence
    d'un enregistrement ordinaire — celle que produit n'importe
    quel éditeur, et qu'Obsidian sait traiter.

    C'est sans danger : le contenu écrit étant identique à celui
    déjà présent, une interruption en cours de route laisse le
    fichier inchangé. La garantie de l'écriture atomique reste
    donc entière.
    """
    try:
        contenu = file_path.read_bytes()

        with open(file_path, "r+b") as fichier:
            fichier.write(contenu)
            fichier.flush()
            os.fsync(fichier.fileno())
    except OSError as error:
        logger.debug(
            "Note non re-signalée à Obsidian (%s) : %s",
            file_path.name,
            error,
        )

        return False

    return True


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"

    if line.endswith("\n"):
        return "\n"

    return ""


def _has_frontmatter(content: str) -> bool:
    lines = content.splitlines()

    return bool(lines) and lines[0].strip() == "---"


def _heading_level(line: str) -> int:
    stripped = line.strip()

    return len(stripped) - len(stripped.lstrip("#"))


def _find_section_end(lines: list[str], section_index: int) -> int:
    """Index de fin d'une section : le prochain titre de même niveau."""
    level = _heading_level(lines[section_index])

    for index in range(section_index + 1, len(lines)):
        stripped = lines[index].strip()

        if not stripped.startswith("#"):
            continue

        if _heading_level(lines[index]) <= level:
            return index

    return len(lines)


def _find_heading(lines: list[str], section: str) -> int | None:
    """Trouve un titre de section, quel que soit son niveau."""
    wanted = section.strip().lstrip("#").strip().casefold()

    for index, line in enumerate(lines):
        stripped = line.strip()

        if not stripped.startswith("#"):
            continue

        title = stripped.lstrip("#").strip().casefold()

        if title == wanted:
            return index

    return None


def validate_frontmatter_text(text: str) -> dict:
    """Contrôle qu'un frontmatter est du YAML exploitable."""
    data = yaml.safe_load(text)

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise VaultWriteError("Le frontmatter n'est pas un mapping.")

    return data
