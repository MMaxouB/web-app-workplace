"""Surveillance du Vault (§28).

Obsidian est souvent ouvert pendant que l'application tourne. Sans
surveillance, une note modifiée dans Obsidian n'apparaît qu'au
prochain rechargement de page : c'était la dernière gêne réelle au
quotidien.

Ce module observe le dossier du Vault et prévient les abonnés dès
qu'une note change. `watchfiles` s'appuie sur inotify côté Linux :
c'est le noyau qui signale les changements, il n'y a aucun parcours
périodique du disque.

Ce qui est volontairement ignoré :

- `.obsidian/` — Obsidian y réécrit `workspace.json` en permanence,
  chaque déplacement de curseur produirait un événement ;
- les fichiers cachés, dont les `.nom.md.tmp` de notre propre writer,
  qui se retrouveraient à annoncer nos écritures deux fois ;
- tout ce qui n'est pas du Markdown.

Le module ne relit rien et ne met rien en cache : il annonce qu'un
changement a eu lieu, et c'est au client de redemander ce dont il a
besoin. Un index mémoire (§27) viendra se brancher ici le jour où le
Vault sera assez gros pour le justifier.
"""

import asyncio
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


# Laisse retomber les rafales : enregistrer une note dans Obsidian
# produit plusieurs événements en quelques millisecondes.
DEBOUNCE_MS = 400


def concerne_le_vault(chemin: str) -> bool:
    """Ce changement mérite-t-il de prévenir l'interface ?"""
    p = Path(chemin)

    if p.suffix.lower() != ".md":
        return False

    if ".obsidian" in p.parts:
        return False

    # Fichiers cachés, dont les temporaires du writer.
    return not any(partie.startswith(".") for partie in p.parts)


class SurveillantVault:
    """Observe le Vault et diffuse les changements aux abonnés.

    Chaque client SSE possède sa propre file. Une file pleine est
    vidée de son plus ancien élément plutôt que de bloquer : un
    navigateur en veille ne doit pas retenir la surveillance.
    """

    def __init__(self, chemin: Path):
        self.chemin = chemin
        self._abonnes: set[asyncio.Queue] = set()
        self._tache: asyncio.Task | None = None
        self._arret: asyncio.Event | None = None

    # =====================================================
    # Abonnements
    # =====================================================

    def abonner(self) -> asyncio.Queue:
        file = asyncio.Queue(maxsize=8)
        self._abonnes.add(file)

        logger.debug("Abonné à la surveillance (%d au total)", len(self._abonnes))

        return file

    def desabonner(self, file: asyncio.Queue) -> None:
        self._abonnes.discard(file)

    @property
    def nombre_abonnes(self) -> int:
        return len(self._abonnes)

    @property
    def actif(self) -> bool:
        return self._tache is not None and not self._tache.done()

    def diffuser(self, message: dict) -> None:
        for file in list(self._abonnes):
            if file.full():
                # Le client ne suit pas : on jette le plus ancien
                # message, qui est de toute façon périmé.
                try:
                    file.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            try:
                file.put_nowait(message)
            except asyncio.QueueFull:
                pass

    # =====================================================
    # Cycle de vie
    # =====================================================

    async def demarrer(self) -> None:
        if self._tache is not None:
            return

        if not self.chemin.is_dir():
            logger.warning(
                "Vault introuvable, surveillance désactivée : %s",
                self.chemin,
            )
            return

        self._arret = asyncio.Event()
        self._tache = asyncio.create_task(self._boucle())

        logger.info("Surveillance du Vault active : %s", self.chemin)

    async def arreter(self) -> None:
        if self._tache is None:
            return

        self._arret.set()
        self._tache.cancel()

        try:
            await self._tache
        except (asyncio.CancelledError, Exception):
            pass

        self._tache = None

        logger.info("Surveillance du Vault arrêtée.")

    async def _boucle(self) -> None:
        """Écoute les changements jusqu'à l'arrêt du serveur."""
        from watchfiles import awatch

        try:
            async for lot in awatch(
                self.chemin,
                stop_event=self._arret,
                debounce=DEBOUNCE_MS,
                recursive=True,
            ):
                chemins = sorted(
                    {
                        chemin
                        for _, chemin in lot
                        if concerne_le_vault(chemin)
                    }
                )

                if not chemins:
                    continue

                noms = [Path(c).name for c in chemins]

                logger.info(
                    "Vault modifié (%d note(s)) : %s",
                    len(noms),
                    ", ".join(noms[:4]) + ("…" if len(noms) > 4 else ""),
                )

                self.diffuser({"type": "vault", "notes": noms})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Une surveillance qui tombe ne doit pas emporter le
            # serveur : l'application reste utilisable, simplement
            # sans rafraîchissement automatique.
            logger.error(
                "Surveillance interrompue (%s) : l'interface "
                "continuera de fonctionner avec le bouton ⟳.",
                error,
            )
