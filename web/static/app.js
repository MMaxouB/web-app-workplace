/* =====================================================
   Vault Web — application
   =====================================================

   Routage par ancre (#/tasks, #/project/<id>…), une fonction de
   rendu par page, aucun état global au-delà du cache de la requête
   en cours. Les données viennent toujours de l'API : le Vault reste
   la source de vérité, l'interface n'est qu'une vue.
   ===================================================== */

const $  = (sel, racine = document) => racine.querySelector(sel);
const $$ = (sel, racine = document) => [...racine.querySelectorAll(sel)];

const contenu = $("#contenu");

// Déclaré tôt : `api()` s'en sert avant que la section
// « rafraîchissement automatique » ne soit atteinte.
let DERNIERE_ECRITURE = 0;

function noterEcriture() {
  DERNIERE_ECRITURE = Date.now();
}

/* =====================================================
   Utilitaires
   ===================================================== */

function echapper(valeur) {
  if (valeur === null || valeur === undefined) return "";
  return String(valeur)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function api(chemin, options = {}) {
  const config = { headers: { Accept: "application/json" }, ...options };

  if (config.corps !== undefined) {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(config.corps);
    delete config.corps;
  }

  // Nos écritures font réagir le surveillant du Vault : on note
  // l'instant pour ignorer l'écho, la vue étant déjà rafraîchie.
  if (config.method && config.method !== "GET") noterEcriture();

  const reponse = await fetch(chemin, config);

  if (!reponse.ok) {
    let detail = `${reponse.status}`;
    try {
      const json = await reponse.json();
      detail = json.detail || detail;
    } catch {
      /* réponse non JSON : on garde le code */
    }
    const erreur = new Error(detail);
    erreur.statut = reponse.status;
    throw erreur;
  }

  return reponse.status === 204 ? null : reponse.json();
}

/* =====================================================
   Toasts
   ===================================================== */

const zoneToasts = $("#toasts");

function toast(titre, detail = "", genre = "succes", duree = 4200) {
  const element = document.createElement("div");
  element.className = `toast toast-${genre}`;
  element.innerHTML = `
    <div class="toast-texte">
      <div class="toast-titre">${echapper(titre)}</div>
      ${detail ? `<div class="toast-detail">${echapper(detail)}</div>` : ""}
    </div>`;

  zoneToasts.appendChild(element);

  setTimeout(() => {
    element.classList.add("sortant");
    setTimeout(() => element.remove(), 220);
  }, duree);
}

/** Un 409 mérite un message plus long : il y a une décision à prendre. */
function signalerErreur(erreur, contexte = "Action impossible") {
  if (erreur.statut === 409) {
    toast(
      "Note modifiée ailleurs",
      erreur.message,
      "attention",
      9000
    );
    return;
  }
  toast(contexte, erreur.message, "erreur", 7000);
  console.error(erreur);
}

const PRIORITES = ["critical", "high", "medium", "low"];

function badgePriorite(priorite) {
  const cle = (priorite || "").toLowerCase();
  const classe = PRIORITES.includes(cle) ? cle : "neutre";
  return `<span class="badge badge-${classe}">${echapper(priorite || "—")}</span>`;
}

const STATUT_LIBELLES = {
  active: "Active",
  waiting: "En attente",
  completed: "Terminée",
  archived: "Archivée",
};

function badgeStatut(statut) {
  const cle = (statut || "").toLowerCase();
  const teintes = { active: "medium", waiting: "high", completed: "low", archived: "neutre" };
  const classe = teintes[cle] || "neutre";
  return `<span class="badge badge-${classe}">${echapper(STATUT_LIBELLES[cle] || statut || "—")}</span>`;
}

/** Rend une échéance lisible, et signale ce qui presse. */
function rendreEcheance(iso) {
  if (!iso) return "";

  const date = new Date(iso + "T00:00:00");
  if (Number.isNaN(date.getTime())) return "";

  const aujourdhui = new Date();
  aujourdhui.setHours(0, 0, 0, 0);

  const jours = Math.round((date - aujourdhui) / 86400000);

  let texte;
  if (jours < 0)        texte = `en retard de ${Math.abs(jours)} j`;
  else if (jours === 0) texte = "aujourd'hui";
  else if (jours === 1) texte = "demain";
  else if (jours <= 7)  texte = `dans ${jours} j`;
  else                  texte = date.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });

  const classe = jours < 0 ? "retard" : jours <= 2 ? "proche" : "";
  return `<span class="echeance ${classe}">${texte}</span>`;
}

function initiales(nom) {
  return (nom || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((mot) => mot[0] || "")
    .join("")
    .toUpperCase();
}

/* =====================================================
   Rendu Markdown minimal
   =====================================================
   Volontairement limité à ce que contiennent les notes du Vault :
   titres, listes, tableaux, code, gras, italique, liens. Pas de
   bibliothèque externe pour une application locale.
   ===================================================== */

function rendreMarkdown(source) {
  if (!source) return `<p class="vide">Cette note n'a pas de contenu.</p>`;

  const lignes = source.split("\n");
  const sortie = [];
  let dansCode = false;
  let dansListe = false;
  let tableau = null;

  const fermerListe = () => { if (dansListe) { sortie.push("</ul>"); dansListe = false; } };

  const fermerTableau = () => {
    if (!tableau) return;
    const [entete, ...corps] = tableau;
    sortie.push("<table><thead><tr>");
    entete.forEach((c) => sortie.push(`<th>${enligne(c)}</th>`));
    sortie.push("</tr></thead><tbody>");
    corps.forEach((rangee) => {
      sortie.push("<tr>");
      rangee.forEach((c) => sortie.push(`<td>${enligne(c)}</td>`));
      sortie.push("</tr>");
    });
    sortie.push("</tbody></table>");
    tableau = null;
  };

  for (const ligne of lignes) {
    if (ligne.trim().startsWith("```")) {
      fermerListe(); fermerTableau();
      sortie.push(dansCode ? "</code></pre>" : "<pre><code>");
      dansCode = !dansCode;
      continue;
    }

    if (dansCode) { sortie.push(echapper(ligne) + "\n"); continue; }

    // Tableaux : | a | b |
    if (/^\s*\|.*\|\s*$/.test(ligne)) {
      const cellules = ligne.trim().slice(1, -1).split("|").map((c) => c.trim());
      // La ligne de séparation |---|---| n'est pas une donnée.
      if (cellules.every((c) => /^:?-{2,}:?$/.test(c))) continue;
      fermerListe();
      (tableau ??= []).push(cellules);
      continue;
    }
    fermerTableau();

    const titre = ligne.match(/^(#{1,6})\s+(.*)$/);
    if (titre) {
      fermerListe();
      const niveau = Math.min(titre[1].length, 3);
      sortie.push(`<h${niveau}>${enligne(titre[2])}</h${niveau}>`);
      continue;
    }

    const puce = ligne.match(/^\s*[-*]\s+(.*)$/);
    if (puce) {
      if (!dansListe) { sortie.push("<ul>"); dansListe = true; }
      const coche = puce[1].match(/^\[([ xX])\]\s*(.*)$/);
      if (coche) {
        const cochee = coche[1].toLowerCase() === "x";
        sortie.push(`<li>${cochee ? "☑" : "☐"} ${enligne(coche[2])}</li>`);
      } else {
        sortie.push(`<li>${enligne(puce[1])}</li>`);
      }
      continue;
    }
    fermerListe();

    if (ligne.trim().startsWith(">")) {
      sortie.push(`<blockquote>${enligne(ligne.replace(/^\s*>\s?/, ""))}</blockquote>`);
      continue;
    }

    if (!ligne.trim()) continue;

    sortie.push(`<p>${enligne(ligne)}</p>`);
  }

  fermerListe();
  fermerTableau();
  if (dansCode) sortie.push("</code></pre>");

  return sortie.join("");
}

function enligne(texte) {
  return echapper(texte)
    // `[^`]*` et non `[^`]+` : le Vault contient des paires vides
    // (« Champ `project` : `` → … »), et exiger au moins un
    // caractère décalait toutes les paires suivantes.
    .replace(/`([^`]*)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/\[\[([^\]]+)\]\]/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

/* =====================================================
   Fragments réutilisables
   ===================================================== */

function carteTache(tache, compacte = false) {
  const meta = [];
  if (tache.project) meta.push(echapper(tache.project));
  if (tache.platform) meta.push(echapper(tache.platform));
  if (tache.collaborator && tache.collaborator.toLowerCase() !== "moi") {
    meta.push(echapper(tache.collaborator));
  }
  if (tache.is_inbox) meta.push("à trier");

  return `
    <a class="tache ${compacte ? "compacte" : ""}" href="#/task/${tache.id}">
      ${badgePriorite(tache.priority)}
      <div class="tache-corps">
        <div class="tache-nom">${echapper(tache.name)}</div>
        ${meta.length ? `<div class="tache-meta">${meta.join('<span class="sep">·</span>')}</div>` : ""}
      </div>
      <div class="tache-fin">
        ${rendreEcheance(tache.due_date)}
        ${compacte ? "" : badgeStatut(tache.status)}
      </div>
    </a>`;
}

function listeTaches(taches, compacte = false, messageVide = "Aucune tâche.") {
  if (!taches.length) return `<p class="vide">${messageVide}</p>`;
  return `<div class="liste-taches">${taches.map((t) => carteTache(t, compacte)).join("")}</div>`;
}

/* =====================================================
   Couleurs sémantiques
   =====================================================
   Chaque libellé connu porte sa couleur : rouge pour ce qui est en
   retard ou critique, orange pour ce qui presse, bleu pour ce qui
   est en cours, vert pour ce qui est fait, gris pour le reste.
   Une couleur qui ne dit rien ne sert à rien (§24).
   ===================================================== */

const TEINTES_SEMANTIQUES = {
  // Priorités
  Critical: "critical",
  High: "high",
  Medium: "medium",
  Low: "low",
  // Statuts
  Active: "medium",
  Waiting: "high",
  Completed: "low",
  Archived: "neutre",
  // Échéances
  "En retard": "critical",
  "Aujourd'hui": "high",
  "48 heures": "high",
  "7 jours": "medium",
  "Plus tard": "accent2",
  "Sans date": "neutre",
};

/* Palette de repli pour les axes sans sémantique — plateformes,
   projets. Les teintes sont distinctes mais de même intensité :
   aucune ne doit paraître plus grave qu'une autre. */
const PALETTE = ["accent", "accent2", "accent3", "accent4", "accent5", "low", "high"];

function teinteDe(libelle, index, forcee) {
  if (forcee === "auto") return PALETTE[index % PALETTE.length];
  if (TEINTES_SEMANTIQUES[libelle]) return TEINTES_SEMANTIQUES[libelle];
  return forcee || PALETTE[index % PALETTE.length];
}

function blocRepartition(entrees, teinte) {
  if (!entrees.some((e) => e.valeur > 0)) return `<p class="vide">Aucune donnée.</p>`;

  const maximum = Math.max(...entrees.map((e) => e.valeur), 1);

  return `<div class="repartition">${entrees
    .map((entree, index) => {
      const couleur = teinteDe(entree.libelle, index, teinte);
      const vide = entree.valeur === 0;

      return `
        <div class="repartition-ligne ${vide ? "zero" : ""}">
          <span class="repartition-libelle" title="${echapper(entree.libelle)}">${echapper(entree.libelle)}</span>
          <span class="repartition-piste">
            <span class="repartition-barre" style="width:${(entree.valeur / maximum) * 100}%; --teinte: var(--${couleur})"></span>
          </span>
          <span class="repartition-valeur">${entree.valeur}</span>
        </div>`;
    })
    .join("")}</div>`;
}

/* =====================================================
   Camembert
   =====================================================
   Un donut en SVG pur : chaque part est un arc de cercle tracé avec
   stroke-dasharray. Pas de bibliothèque — le calcul tient en dix
   lignes et le rendu reste net à toutes les tailles.
   ===================================================== */

function camembert(entrees, { taille = 168, epaisseur = 26, teinte, centre } = {}) {
  const donnees = entrees.filter((e) => e.valeur > 0);

  if (!donnees.length) return `<p class="vide">Aucune donnée.</p>`;

  const total = donnees.reduce((somme, e) => somme + e.valeur, 0);

  const rayon = (taille - epaisseur) / 2;
  const perimetre = 2 * Math.PI * rayon;

  let parcouru = 0;

  const arcs = donnees
    .map((entree) => {
      const index = entrees.indexOf(entree);
      const couleur = teinteDe(entree.libelle, index, teinte);

      const part = entree.valeur / total;
      const longueur = part * perimetre;

      // Un décalage négatif fait avancer le départ de l'arc.
      const decalage = -parcouru * perimetre;
      parcouru += part;

      return `<circle class="part" cx="${taille / 2}" cy="${taille / 2}" r="${rayon}"
        fill="none" stroke="var(--${couleur})" stroke-width="${epaisseur}"
        stroke-dasharray="${longueur.toFixed(2)} ${(perimetre - longueur).toFixed(2)}"
        stroke-dashoffset="${decalage.toFixed(2)}"
        transform="rotate(-90 ${taille / 2} ${taille / 2})">
        <title>${echapper(entree.libelle)} : ${entree.valeur}</title>
      </circle>`;
    })
    .join("");

  const legende = donnees
    .map((entree) => {
      const index = entrees.indexOf(entree);
      const couleur = teinteDe(entree.libelle, index, teinte);
      const pourcent = Math.round((entree.valeur / total) * 100);

      return `<div class="legende-ligne">
        <span class="legende-pastille" style="background: var(--${couleur})"></span>
        <span class="legende-libelle" title="${echapper(entree.libelle)}">${echapper(entree.libelle)}</span>
        <span class="legende-valeur">${entree.valeur}<span class="legende-pct"> · ${pourcent}%</span></span>
      </div>`;
    })
    .join("");

  return `
    <div class="camembert-bloc">
      <div class="camembert">
        <svg viewBox="0 0 ${taille} ${taille}" width="${taille}" height="${taille}" role="img">
          <circle cx="${taille / 2}" cy="${taille / 2}" r="${rayon}" fill="none"
                  stroke="var(--carte-haut)" stroke-width="${epaisseur}"></circle>
          ${arcs}
        </svg>
        ${
          centre
            ? `<div class="camembert-centre">
                 <div class="camembert-valeur">${echapper(centre.valeur)}</div>
                 <div class="camembert-libelle">${echapper(centre.libelle)}</div>
               </div>`
            : ""
        }
      </div>
      <div class="legende">${legende}</div>
    </div>`;
}

function barreProgression(progression, grande = false) {
  const termine = progression.pourcentage >= 100;
  return `
    <div class="progression-grande">
      <div class="progression-chiffres">
        <span class="progression-pct">${progression.pourcentage}%</span>
        <span class="progression-detail">${progression.termine} / ${progression.total} tâches</span>
      </div>
      <div class="barre ${grande ? "grande" : ""}">
        <div class="barre-remplie ${termine ? "termine" : ""}" style="width:${progression.pourcentage}%"></div>
      </div>
    </div>`;
}

/* =====================================================
   Pages
   ===================================================== */

async function pageDashboard() {
  const d = await api("/api/dashboard");

  const compteurs = [
    { valeur: d.compteurs.taches_ouvertes, libelle: "Tâches ouvertes", teinte: "medium" },
    { valeur: d.compteurs.taches_urgentes, libelle: "Urgentes",        teinte: "high" },
    { valeur: d.compteurs.projets_actifs,  libelle: "Projets actifs",  teinte: "low" },
    { valeur: d.compteurs.en_retard,       libelle: "En retard",       teinte: "critical" },
  ];

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Dashboard</h1>
        <p class="page-sous-titre">Qu'est-ce qui mérite mon attention maintenant ?</p>
      </div>
    </div>

    <div class="grille-compteurs">
      ${compteurs
        .map(
          (c) => `
        <div class="compteur" style="--teinte: var(--${c.teinte})">
          <div class="compteur-valeur">${c.valeur}</div>
          <div class="compteur-libelle">${c.libelle}</div>
        </div>`
        )
        .join("")}
    </div>

    <div class="grille-2">
      <section class="carte">
        <h2 class="carte-titre">Progression globale</h2>
        ${barreProgression(d.progression, true)}
        <div style="margin-top:22px">
          <h2 class="carte-titre">Ce qui presse</h2>
          ${blocRepartition(d.echeances.compteurs.slice(0, 4))}
        </div>
      </section>

      <section class="carte">
        <h2 class="carte-titre">Santé du workspace</h2>
        ${d.sante.indicateurs
          .map(
            (i) => `
          <div class="indicateur">
            <span class="indicateur-point niveau-${i.niveau}"></span>
            <span class="indicateur-domaine">${echapper(i.domaine)}</span>
            <span class="indicateur-detail">${echapper(i.detail)}</span>
          </div>`
          )
          .join("")}
      </section>
    </div>

    <section class="carte" style="margin-bottom:16px">
      <h2 class="carte-titre">À faire maintenant</h2>
      ${listeTaches(d.urgent, true, "Rien d'urgent. Profites-en.")}
    </section>

    <div class="grille-3">
      <section class="carte">
        <h2 class="carte-titre">Par priorité — tâches ouvertes</h2>
        ${camembert(d.repartitions.priorites, {
          centre: {
            valeur: d.repartitions.priorites.reduce((s, e) => s + e.valeur, 0),
            libelle: "ouvertes",
          },
        })}
      </section>
      <section class="carte">
        <h2 class="carte-titre">Par plateforme</h2>
        ${camembert(d.repartitions.plateformes, {
          teinte: "auto",
          centre: {
            valeur: d.repartitions.plateformes.filter((e) => e.valeur > 0).length,
            libelle: "domaines",
          },
        })}
      </section>
      <section class="carte">
        <h2 class="carte-titre">Échéances — tâches ouvertes</h2>
        ${camembert(d.echeances.compteurs, {
          centre: {
            valeur: d.echeances.compteurs.reduce((s, e) => s + e.valeur, 0),
            libelle: "à faire",
          },
        })}
      </section>
    </div>

    <div class="grille-2">
      <section class="carte">
        <h2 class="carte-titre">Charge par projet — tâches ouvertes</h2>
        ${blocRepartition(d.repartitions.projets, "auto")}
      </section>
      <section class="carte">
        <h2 class="carte-titre">Avancement</h2>
        ${blocRepartition(d.repartitions.statuts)}
        <p class="note-carte">
          Le seul bloc qui compte les tâches terminées : c'est son objet.
          Les archivées en sont exclues, elles ne sont ni faites ni à faire.
        </p>
      </section>
    </div>`;
}

async function pageInbox() {
  const { items } = await api("/api/tasks");
  const aTrier = items.filter((t) => t.is_inbox);
  const sansProjet = items.filter((t) => t.is_open && !t.project && !t.is_inbox);
  const sansEcheance = items.filter((t) => t.is_open && !t.due_date && !t.is_inbox);

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Inbox</h1>
        <p class="page-sous-titre">Ce qui attend une décision</p>
      </div>
      <button class="btn btn-primaire" data-action="capture-page">⚡ Capture rapide</button>
    </div>

    <section class="carte" style="margin-bottom:16px">
      <h2 class="carte-titre">Captures à trier — ${aTrier.length}</h2>
      ${listeTaches(aTrier, true, "L'inbox est vide.")}
    </section>

    <section class="carte" style="margin-bottom:16px">
      <h2 class="carte-titre">Tâches ouvertes sans projet — ${sansProjet.length}</h2>
      ${listeTaches(sansProjet, true, "Toutes les tâches ouvertes sont rattachées.")}
    </section>

    <section class="carte">
      <h2 class="carte-titre">Tâches ouvertes sans échéance — ${sansEcheance.length}</h2>
      ${listeTaches(sansEcheance, true, "Toutes les tâches ouvertes ont une échéance.")}
    </section>`;
}

const FILTRES_TACHES = { statut: "", priorite: "", projet: "", plateforme: "" };

let VUE_TACHES = "liste";

async function pageTaches() {
  const { items } = await api("/api/tasks");

  const projets = [...new Set(items.map((t) => t.project).filter(Boolean))].sort();
  const plateformes = [...new Set(items.map((t) => t.platform).filter(Boolean))].sort();

  const filtrees = items.filter(
    (t) =>
      (!FILTRES_TACHES.statut || t.status === FILTRES_TACHES.statut) &&
      (!FILTRES_TACHES.priorite || t.priority === FILTRES_TACHES.priorite) &&
      (!FILTRES_TACHES.projet || t.project === FILTRES_TACHES.projet) &&
      (!FILTRES_TACHES.plateforme || t.platform === FILTRES_TACHES.plateforme)
  );

  const onglets = [
    ["", "Toutes"],
    ["active", "Actives"],
    ["waiting", "En attente"],
    ["completed", "Terminées"],
    ["archived", "Archives"],
  ];

  const vues = [
    ["liste", "Liste"],
    ["kanban", "Kanban"],
    ["calendrier", "Calendrier"],
  ];

  const options = (liste, courant) =>
    liste.map((v) => `<option value="${echapper(v)}" ${v === courant ? "selected" : ""}>${echapper(v)}</option>`).join("");

  // Le kanban a ses propres colonnes de statut, le calendrier range
  // par date : le filtre par statut n'a de sens qu'en liste.
  const corps = {
    liste: () => listeTaches(filtrees, false, "Aucune tâche ne correspond à ces filtres."),
    kanban: () => vueKanban(items),
    calendrier: () => vueCalendrier(items),
  }[VUE_TACHES]();

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Tâches</h1>
        <p class="page-sous-titre">
          ${VUE_TACHES === "liste" ? `${filtrees.length} sur ${items.length}` : `${items.length} tâches`}
        </p>
      </div>
      <button class="btn btn-primaire" data-action="nouvelle-tache-page">+ Nouvelle tâche</button>
    </div>

    <div class="barre-vues">
      <div class="onglets">
        ${vues
          .map(
            ([valeur, libelle]) =>
              `<button class="onglet ${VUE_TACHES === valeur ? "actif" : ""}" data-vue="${valeur}">${libelle}</button>`
          )
          .join("")}
      </div>

      ${
        VUE_TACHES === "liste"
          ? `<div class="onglets">
               ${onglets
                 .map(
                   ([valeur, libelle]) =>
                     `<button class="onglet ${FILTRES_TACHES.statut === valeur ? "actif" : ""}" data-statut="${valeur}">${libelle}</button>`
                 )
                 .join("")}
             </div>`
          : ""
      }
    </div>

    ${
      VUE_TACHES === "calendrier"
        ? ""
        : `<div class="filtres">
             <select data-filtre="priorite">
               <option value="">Toutes priorités</option>
               ${options(PRIORITES, FILTRES_TACHES.priorite)}
             </select>
             <select data-filtre="projet">
               <option value="">Tous projets</option>
               ${options(projets, FILTRES_TACHES.projet)}
             </select>
             <select data-filtre="plateforme">
               <option value="">Toutes plateformes</option>
               ${options(plateformes, FILTRES_TACHES.plateforme)}
             </select>
           </div>`
    }

    ${corps}`;
}

/* =====================================================
   Vue Kanban (§8)
   =====================================================
   Trois colonnes, glisser une carte change son statut — donc
   déplace le fichier dans le Vault. Le glisser-déposer utilise
   l'API HTML5 native : rien à installer.
   ===================================================== */

const COLONNES_KANBAN = [
  { statut: "active", titre: "Active", teinte: "medium" },
  { statut: "waiting", titre: "En attente", teinte: "high" },
  { statut: "completed", titre: "Terminée", teinte: "low" },
];

function vueKanban(items) {
  const colonnes = COLONNES_KANBAN.map((colonne) => {
    const cartes = items
      .filter((t) => t.status === colonne.statut)
      .filter(
        (t) =>
          (!FILTRES_TACHES.priorite || t.priority === FILTRES_TACHES.priorite) &&
          (!FILTRES_TACHES.projet || t.project === FILTRES_TACHES.projet) &&
          (!FILTRES_TACHES.plateforme || t.platform === FILTRES_TACHES.plateforme)
      );

    return `
      <section class="colonne" data-statut="${colonne.statut}">
        <header class="colonne-tete" style="--teinte: var(--${colonne.teinte})">
          <span class="colonne-titre">${colonne.titre}</span>
          <span class="colonne-compte">${cartes.length}</span>
        </header>
        <div class="colonne-corps" data-depot="${colonne.statut}">
          ${
            cartes.length
              ? cartes.map((t) => carteKanban(t)).join("")
              : `<p class="colonne-vide">Déposer une tâche ici</p>`
          }
        </div>
      </section>`;
  }).join("");

  return `<div class="kanban">${colonnes}</div>`;
}

function carteKanban(tache) {
  const meta = [tache.project, tache.platform].filter(Boolean);

  return `
    <article class="carte-kanban" draggable="true"
             data-id="${tache.id}" data-version="${tache.version || ""}"
             data-statut="${tache.status}">
      <div class="carte-kanban-tete">
        ${badgePriorite(tache.priority)}
        ${rendreEcheance(tache.due_date)}
      </div>
      <a class="carte-kanban-nom" href="#/task/${tache.id}">${echapper(tache.name)}</a>
      ${meta.length ? `<div class="carte-kanban-meta">${meta.map(echapper).join(" · ")}</div>` : ""}
    </article>`;
}

function brancherKanban() {
  const kanban = $(".kanban");
  if (!kanban) return;

  let portee = null;

  $$(".carte-kanban", kanban).forEach((carte) => {
    carte.addEventListener("dragstart", (evenement) => {
      portee = carte;
      carte.classList.add("en-vol");
      evenement.dataTransfer.effectAllowed = "move";
      // Firefox exige une donnée pour démarrer le glisser.
      evenement.dataTransfer.setData("text/plain", carte.dataset.id);
    });

    carte.addEventListener("dragend", () => {
      carte.classList.remove("en-vol");
      $$(".colonne-corps", kanban).forEach((c) => c.classList.remove("survolee"));
      portee = null;
    });
  });

  $$(".colonne-corps", kanban).forEach((zone) => {
    zone.addEventListener("dragover", (evenement) => {
      evenement.preventDefault();
      evenement.dataTransfer.dropEffect = "move";
      zone.classList.add("survolee");
    });

    zone.addEventListener("dragleave", () => zone.classList.remove("survolee"));

    zone.addEventListener("drop", async (evenement) => {
      evenement.preventDefault();
      zone.classList.remove("survolee");

      if (!portee) return;

      const nouveau = zone.dataset.depot;
      const { id, statut, version } = portee.dataset;

      if (statut === nouveau) return;

      // Déplacement optimiste : la carte bouge tout de suite, on
      // corrige au rafraîchissement si le serveur refuse.
      zone.appendChild(portee);

      try {
        const resultat = await api(`/api/tasks/${id}`, {
          method: "PATCH",
          corps: { status: nouveau, version: version ? Number(version) : undefined },
        });
        toast("Statut modifié", `${resultat.name} → dossier ${resultat.folder}`);
        await Promise.all([rendre(), majCompteurs()]);
      } catch (erreur) {
        signalerErreur(erreur, "Déplacement refusé");
        await rendre();
      }
    });
  });
}

/* =====================================================
   Vue Calendrier (§9)
   ===================================================== */

let MOIS_AFFICHE = null;

function moisCourant() {
  if (!MOIS_AFFICHE) {
    const aujourdhui = new Date();
    MOIS_AFFICHE = { annee: aujourdhui.getFullYear(), mois: aujourdhui.getMonth() };
  }
  return MOIS_AFFICHE;
}

const NOMS_MOIS = [
  "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
  "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
];

function vueCalendrier(items) {
  const { annee, mois } = moisCourant();

  const premier = new Date(annee, mois, 1);
  const nbJours = new Date(annee, mois + 1, 0).getDate();

  // getDay() met dimanche à 0 ; la semaine commence lundi ici.
  const decalage = (premier.getDay() + 6) % 7;

  // Une tâche archivée est abandonnée : son échéance ne veut plus
  // rien dire, et l'afficher encombrerait le mois pour rien. Leur
  // nombre reste annoncé — masquer sans le dire ferait croire à un
  // calendrier incomplet.
  const affichables = items.filter((t) => t.status !== "archived");
  const masquees = items.length - affichables.length;

  const parJour = {};
  let sansDate = 0;

  affichables.forEach((tache) => {
    if (!tache.due_date) {
      if (tache.is_open) sansDate += 1;
      return;
    }
    (parJour[tache.due_date] ??= []).push(tache);
  });

  const aujourdhui = new Date();
  const cleAujourdhui = [
    aujourdhui.getFullYear(),
    String(aujourdhui.getMonth() + 1).padStart(2, "0"),
    String(aujourdhui.getDate()).padStart(2, "0"),
  ].join("-");

  const cellules = [];

  for (let i = 0; i < decalage; i += 1) {
    cellules.push(`<div class="jour hors-mois"></div>`);
  }

  for (let jour = 1; jour <= nbJours; jour += 1) {
    const cle = `${annee}-${String(mois + 1).padStart(2, "0")}-${String(jour).padStart(2, "0")}`;
    const taches = parJour[cle] || [];

    cellules.push(`
      <div class="jour ${cle === cleAujourdhui ? "aujourdhui" : ""}" data-jour="${cle}">
        <div class="jour-numero">${jour}</div>
        <div class="jour-taches">
          ${taches
            .map(
              (t) => `<a class="pastille-tache ${t.status === "completed" ? "faite" : ""}"
                         draggable="true"
                         data-id="${t.id}" data-version="${t.version || ""}"
                         data-jour="${cle}"
                         href="#/task/${t.id}"
                         style="--teinte: var(--${PRIORITES.includes((t.priority || "").toLowerCase()) ? t.priority.toLowerCase() : "neutre"})"
                         title="${echapper(t.name)}${t.project ? " — " + echapper(t.project) : ""}${t.status === "completed" ? " (terminée)" : ""}">
                        ${echapper(t.name)}
                      </a>`
            )
            .join("")}
        </div>
      </div>`);
  }

  return `
    <div class="calendrier-barre">
      <button class="btn" data-mois="-1">←</button>
      <span class="calendrier-titre">${NOMS_MOIS[mois]} ${annee}</span>
      <button class="btn" data-mois="1">→</button>
      <button class="btn" data-mois="0">Aujourd'hui</button>
      <span class="calendrier-note">
        ${sansDate ? `${sansDate} ouverte${sansDate > 1 ? "s" : ""} sans échéance` : ""}
        ${sansDate && masquees ? " · " : ""}
        ${masquees ? `${masquees} archivée${masquees > 1 ? "s" : ""} masquée${masquees > 1 ? "s" : ""}` : ""}
      </span>
    </div>

    <div class="calendrier">
      ${["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        .map((j) => `<div class="entete-jour">${j}</div>`)
        .join("")}
      ${cellules.join("")}
    </div>`;
}

function brancherCalendrier() {
  const calendrier = $(".calendrier");
  if (!calendrier) return;

  $$("[data-mois]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      const pas = Number(bouton.dataset.mois);

      if (pas === 0) {
        MOIS_AFFICHE = null;
      } else {
        const { annee, mois } = moisCourant();
        const nouveau = new Date(annee, mois + pas, 1);
        MOIS_AFFICHE = { annee: nouveau.getFullYear(), mois: nouveau.getMonth() };
      }

      rendre();
    })
  );

  let portee = null;

  $$(".pastille-tache", calendrier).forEach((pastille) => {
    pastille.addEventListener("dragstart", (evenement) => {
      portee = pastille;
      pastille.classList.add("en-vol");
      evenement.dataTransfer.effectAllowed = "move";
      evenement.dataTransfer.setData("text/plain", pastille.dataset.id);
    });

    pastille.addEventListener("dragend", () => {
      pastille.classList.remove("en-vol");
      $$(".jour", calendrier).forEach((j) => j.classList.remove("survole"));
      portee = null;
    });
  });

  $$(".jour[data-jour]", calendrier).forEach((jour) => {
    jour.addEventListener("dragover", (evenement) => {
      evenement.preventDefault();
      jour.classList.add("survole");
    });

    jour.addEventListener("dragleave", () => jour.classList.remove("survole"));

    jour.addEventListener("drop", async (evenement) => {
      evenement.preventDefault();
      jour.classList.remove("survole");

      if (!portee) return;

      const cible = jour.dataset.jour;
      const { id, version, jour: origine } = portee.dataset;

      if (cible === origine) return;

      try {
        const resultat = await api(`/api/tasks/${id}`, {
          method: "PATCH",
          corps: { due_date: cible, version: version ? Number(version) : undefined },
        });
        toast("Échéance déplacée", `${resultat.name} → ${resultat.deadline}`);
        await Promise.all([rendre(), majCompteurs()]);
      } catch (erreur) {
        signalerErreur(erreur, "Déplacement refusé");
        await rendre();
      }
    });
  });
}

function brancherFiltresTaches() {
  $$(".onglet[data-statut]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      FILTRES_TACHES.statut = bouton.dataset.statut;
      rendre();
    })
  );

  $$(".onglet[data-vue]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      VUE_TACHES = bouton.dataset.vue;
      rendre();
    })
  );

  $$("select[data-filtre]").forEach((select) =>
    select.addEventListener("change", () => {
      FILTRES_TACHES[select.dataset.filtre] = select.value;
      rendre();
    })
  );
}

async function pageTache(id) {
  const [t, m] = await Promise.all([api(`/api/tasks/${id}`), meta()]);

  const projets = ["", ...new Set([...m.projets, ...m.projets_cites])].filter(
    (valeur, index, tout) => index === tout.indexOf(valeur)
  );

  const fige = (cle, rendu) => `<dd>${rendu}</dd>`;

  const lignes = [
    ["Statut", ddEditable("status", t.status, badgeStatut(t.status), m.statuts)],
    ["Priorité", ddEditable("priority", t.priority, badgePriorite(t.priority), m.priorites)],
    [
      "Projet",
      ddEditable(
        "project",
        t.project,
        t.project ? echapper(t.project) : "—",
        projets.map((p) => [p, p || "— Aucun —"])
      ),
    ],
    [
      "Plateforme",
      ddEditable(
        "platform",
        t.platform,
        t.platform ? `<span class="etiquette">${echapper(t.platform)}</span>` : "—",
        m.plateformes
      ),
    ],
    ["Collaborateur", ddEditable("collaborator", t.collaborator, echapper(t.collaborator || "—"))],
    [
      "Délai",
      ddEditable(
        "deadline",
        t.deadline,
        t.deadline ? `<span class="etiquette">${echapper(t.deadline)}</span>` : "—",
        m.delais
      ),
    ],
    ["Échéance", fige("due", t.due_date ? rendreEcheance(t.due_date) : echapper(t.due || "—"))],
    ["Créée le", fige("created", echapper((t.created || "—").replace("T", " ").slice(0, 16)))],
    ["Terminée le", fige("completed", echapper(t.completed || "—"))],
    ["Dossier", fige("folder", `<span class="etiquette">${echapper(t.folder)}</span>`)],
  ];

  const suivant = { active: "completed", waiting: "active", completed: "active", archived: "active" };
  const libelleSuivant = {
    active: "Marquer terminée",
    waiting: "Reprendre",
    completed: "Rouvrir",
    archived: "Réactiver",
  };

  return `
    <a class="retour" href="#/tasks">← Tâches</a>

    <div class="fiche-tete">
      <div class="fiche-titre-ligne">
        <h1 class="fiche-titre">${echapper(t.name)}</h1>
        ${badgePriorite(t.priority)}
        ${badgeStatut(t.status)}
      </div>
      <div class="actions-fiche">
        <button class="btn btn-primaire" data-action="statut-suivant"
                data-id="${t.id}" data-statut="${suivant[t.status] || "active"}"
                data-version="${t.version}">
          ${libelleSuivant[t.status] || "Activer"}
        </button>
        <button class="btn" data-action="note" data-genre="tasks" data-id="${t.id}"
                data-nom="${echapper(t.name)}">Ajouter une note</button>
        ${
          t.status !== "archived"
            ? `<button class="btn btn-danger" data-action="archiver" data-genre="tasks"
                       data-id="${t.id}" data-nom="${echapper(t.name)}"
                       data-version="${t.version}">Archiver</button>`
            : ""
        }
      </div>
    </div>

    <div class="grille-2">
      <section class="carte">
        <h2 class="carte-titre">Propriétés — cliquer pour modifier</h2>
        <dl class="proprietes" data-genre="tasks" data-id="${t.id}" data-version="${t.version}">
          ${lignes.map(([cle, dd]) => `<div class="propriete"><dt>${cle}</dt>${dd}</div>`).join("")}
        </dl>
      </section>

      <section class="carte">
        <h2 class="carte-titre">Contenu de la note</h2>
        <div class="markdown zone-defilante">${rendreMarkdown(t.body)}</div>
      </section>
    </div>`;
}

let FILTRE_PROJETS = "";

async function pageProjets() {
  const { items } = await api("/api/projects");

  const filtres = FILTRE_PROJETS ? items.filter((p) => p.status === FILTRE_PROJETS) : items;

  const onglets = [
    ["", "Tous"],
    ["active", "Actifs"],
    ["waiting", "En attente"],
    ["completed", "Terminés"],
    ["archived", "Archives"],
  ];

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Projets</h1>
        <p class="page-sous-titre">${filtres.length} sur ${items.length}</p>
      </div>
      <button class="btn btn-primaire" data-action="nouveau-projet-page">+ Nouveau projet</button>
    </div>

    <div class="onglets">
      ${onglets
        .map(
          ([valeur, libelle]) =>
            `<button class="onglet ${FILTRE_PROJETS === valeur ? "actif" : ""}" data-projet-statut="${valeur}">${libelle}</button>`
        )
        .join("")}
    </div>

    ${
      filtres.length
        ? `<div class="grille-projets">${filtres
            .map(
              (p) => `
        <a class="projet" href="#/project/${p.id}">
          <div class="projet-tete">
            <span class="projet-nom">${echapper(p.name)}</span>
          </div>
          <div class="projet-meta">
            ${badgeStatut(p.status)}
            ${p.priority ? badgePriorite(p.priority) : ""}
            ${p.category ? `<span class="etiquette">${echapper(p.category)}</span>` : ""}
          </div>
          <div class="barre">
            <div class="barre-remplie ${p.progression.pourcentage >= 100 ? "termine" : ""}" style="width:${p.progression.pourcentage}%"></div>
          </div>
          <div class="projet-pied">
            <span>${p.progression.pourcentage}%</span>
            <span>${p.progression.termine} / ${p.progression.total} tâches</span>
          </div>
        </a>`
            )
            .join("")}</div>`
        : `<p class="vide">Aucun projet avec ce statut.</p>`
    }`;
}

function brancherFiltresProjets() {
  $$(".onglet[data-projet-statut]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      FILTRE_PROJETS = bouton.dataset.projetStatut;
      rendre();
    })
  );
}

async function pageProjet(id) {
  const [p, stats, m] = await Promise.all([
    api(`/api/projects/${id}`),
    api(`/api/projects/${id}/stats`),
    meta(),
  ]);

  const ouvertes = p.taches.filter((t) => t.is_open);
  const terminees = p.taches.filter((t) => !t.is_open);

  const lignes = [
    ["Statut", ddEditable("status", p.status, badgeStatut(p.status), m.statuts)],
    [
      "Priorité",
      ddEditable("priority", p.priority, p.priority ? badgePriorite(p.priority) : "—", m.priorites),
    ],
    [
      "Catégorie",
      ddEditable(
        "category",
        p.category,
        p.category ? `<span class="etiquette">${echapper(p.category)}</span>` : "—"
      ),
    ],
    ["Deadline", ddEditable("deadline", p.deadline, echapper(p.deadline || "—"))],
    ["Créé le", `<dd>${echapper((p.created || "—").toString().slice(0, 10))}</dd>`],
    [
      "Repository",
      ddEditable(
        "repository",
        p.repository,
        p.repository
          ? `<a href="${echapper(p.repository)}" target="_blank" rel="noopener" style="color:var(--accent)">${echapper(p.repository)}</a>`
          : "—",
        null,
        "url"
      ),
    ],
    ["Fichier", `<dd><span class="etiquette">${echapper(p.filename)}.md</span></dd>`],
  ];

  return `
    <a class="retour" href="#/projects">← Projets</a>

    <div class="fiche-tete">
      <div class="fiche-titre-ligne">
        <h1 class="fiche-titre">${echapper(p.name)}</h1>
        ${badgeStatut(p.status)}
        ${p.priority ? badgePriorite(p.priority) : ""}
      </div>
      ${barreProgression(p.progression, true)}
      <div class="actions-fiche">
        <button class="btn btn-primaire" data-action="nouvelle-tache-projet"
                data-projet="${echapper(p.name)}">+ Nouvelle tâche</button>
        <button class="btn" data-action="note" data-genre="projects" data-id="${p.id}"
                data-nom="${echapper(p.name)}">Ajouter une note</button>
        ${
          p.status !== "archived"
            ? `<button class="btn btn-danger" data-action="archiver" data-genre="projects"
                       data-id="${p.id}" data-nom="${echapper(p.name)}"
                       data-version="${p.version}">Archiver</button>`
            : ""
        }
      </div>
    </div>

    <div class="grille-3">
      <section class="carte">
        <h2 class="carte-titre">État des tâches</h2>
        ${camembert(stats.statuts, {
          taille: 152,
          epaisseur: 24,
          centre: { valeur: `${p.progression.pourcentage}%`, libelle: "fait" },
        })}
      </section>
      <section class="carte">
        <h2 class="carte-titre">Priorités ouvertes</h2>
        ${camembert(stats.priorites, { taille: 152, epaisseur: 24 })}
      </section>
      <section class="carte">
        <h2 class="carte-titre">Propriétés — cliquer pour modifier</h2>
        <dl class="proprietes" data-genre="projects" data-id="${p.id}" data-version="${p.version}">
          ${lignes.map(([cle, dd]) => `<div class="propriete"><dt>${cle}</dt>${dd}</div>`).join("")}
        </dl>
      </section>
    </div>

    <div class="grille-2">
      <section class="carte">
        <h2 class="carte-titre">Tâches ouvertes — ${ouvertes.length}</h2>
        ${listeTaches(ouvertes, true, "Aucune tâche ouverte sur ce projet.")}
        ${
          terminees.length
            ? `<h2 class="carte-titre" style="margin-top:20px">Terminées — ${terminees.length}</h2>
               ${listeTaches(terminees, true)}`
            : ""
        }
      </section>

      <section class="carte">
        <h2 class="carte-titre">Note du projet</h2>
        <div class="markdown zone-defilante">${rendreMarkdown(p.body)}</div>
      </section>
    </div>`;
}

async function pageCollaborateurs() {
  const { items } = await api("/api/collaborators");

  if (!items.length) return `<p class="vide">Aucun collaborateur.</p>`;

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Collaborateurs</h1>
        <p class="page-sous-titre">${items.length} fiche${items.length > 1 ? "s" : ""}</p>
      </div>
      <button class="btn btn-primaire" data-action="nouveau-collab-page">+ Nouveau</button>
    </div>

    <div class="liste-taches">
      ${items
        .map(
          (c) => `
        <a class="collab" href="#/collaborator/${c.id}">
          <span class="avatar">${echapper(initiales(c.name))}</span>
          <div class="tache-corps">
            <div class="tache-nom">${echapper(c.name)}</div>
            <div class="tache-meta">
              ${c.role ? echapper(c.role) : "rôle non précisé"}
              ${c.discord ? `<span class="sep">·</span>${echapper(c.discord)}` : ""}
            </div>
          </div>
          <div class="tache-fin">
            <span class="echeance">${c.taches_actives} active${c.taches_actives > 1 ? "s" : ""} / ${c.taches}</span>
            ${badgeStatut(c.status)}
          </div>
        </a>`
        )
        .join("")}
    </div>`;
}

async function pageCollaborateur(id) {
  const [c, m] = await Promise.all([api(`/api/collaborators/${id}`), meta()]);

  // Tous les champs restent visibles même vides : sinon on ne peut
  // pas cliquer dessus pour les remplir.
  const champs = [
    ["Statut", "status", c.status, badgeStatut(c.status), m.statuts_collaborateur],
    ["Rôle", "role", c.role, echapper(c.role || "—")],
    ["Société", "company", c.company, echapper(c.company || "—")],
    ["Discord", "discord", c.discord, echapper(c.discord || "—")],
    ["Email", "email", c.email, echapper(c.email || "—")],
    ["GitHub", "github", c.github, echapper(c.github || "—")],
    ["Site", "website", c.website, echapper(c.website || "—")],
    ["Fuseau", "timezone", c.timezone, echapper(c.timezone || "—")],
  ];

  const ouvertes = c.taches.filter((t) => t.is_open);
  const progression = {
    termine: c.taches.length - ouvertes.length,
    total: c.taches.length,
    pourcentage: c.taches.length
      ? Math.round(((c.taches.length - ouvertes.length) * 100) / c.taches.length)
      : 0,
  };

  const parPriorite = ["critical", "high", "medium", "low"].map((cle) => ({
    libelle: cle[0].toUpperCase() + cle.slice(1),
    valeur: ouvertes.filter((t) => (t.priority || "").toLowerCase() === cle).length,
  }));

  return `
    <a class="retour" href="#/collaborators">← Collaborateurs</a>

    <div class="fiche-tete">
      <div class="fiche-titre-ligne">
        <span class="avatar" style="width:44px;height:44px;font-size:16px">${echapper(initiales(c.name))}</span>
        <h1 class="fiche-titre">${echapper(c.name)}</h1>
        ${badgeStatut(c.status)}
        ${c.role ? `<span class="etiquette">${echapper(c.role)}</span>` : ""}
      </div>
      <div class="actions-fiche">
        <button class="btn btn-primaire" data-action="nouvelle-tache-collab"
                data-collab="${echapper(c.name)}">+ Lui assigner une tâche</button>
        <button class="btn" data-action="note" data-genre="collaborators" data-id="${c.id}"
                data-nom="${echapper(c.name)}">Ajouter une note</button>
      </div>
    </div>

    <div class="grille-2">
      <section class="carte">
        <h2 class="carte-titre">Fiche — cliquer pour modifier</h2>
        <dl class="proprietes" data-genre="collaborators" data-id="${c.id}" data-version="${c.version}">
          ${champs
            .map(
              ([libelle, champ, valeur, rendu, options]) =>
                `<div class="propriete"><dt>${libelle}</dt>${ddEditable(champ, valeur, rendu, options)}</div>`
            )
            .join("")}
          <div class="propriete"><dt>Depuis</dt><dd>${echapper(c.joined || "—")}</dd></div>
          <div class="propriete"><dt>Fichier</dt><dd><span class="etiquette">${echapper(c.filename)}.md</span></dd></div>
        </dl>
      </section>

      <section class="carte">
        <h2 class="carte-titre">Tâches — ${c.taches.length}</h2>
        ${
          c.taches.length
            ? `${barreProgression(progression)}
               <div style="margin-top:18px">
                 ${listeTaches(c.taches, true)}
               </div>`
            : `<p class="vide">Aucune tâche ne lui est rattachée.</p>`
        }
      </section>
    </div>

    ${
      ouvertes.length
        ? `<section class="carte" style="margin-top:16px">
             <h2 class="carte-titre">Charge ouverte par priorité</h2>
             ${camembert(parPriorite, { taille: 152, epaisseur: 24 })}
           </section>`
        : ""
    }

    <section class="carte" style="margin-top:16px">
      <h2 class="carte-titre">Note</h2>
      <div class="markdown zone-defilante">${rendreMarkdown(c.body)}</div>
    </section>`;
}

async function pageRecherche(requete) {
  if (!requete) {
    return `
      <div class="page-tete"><div><h1 class="page-titre">Recherche</h1></div></div>
      <p class="vide">Tape quelque chose dans la barre du haut.</p>`;
  }

  const r = await api(`/api/search?q=${encodeURIComponent(requete)}`);

  const groupe = (titre, elements, rendu) =>
    elements.length
      ? `<section class="groupe-resultats">
           <h2 class="carte-titre">${titre} — ${elements.length}</h2>
           ${rendu}
         </section>`
      : "";

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Recherche</h1>
        <p class="page-sous-titre">${r.total} résultat${r.total > 1 ? "s" : ""} pour « ${echapper(requete)} »</p>
      </div>
    </div>

    ${groupe(
      "Projets",
      r.projects,
      `<div class="liste-taches">${r.projects
        .map(
          (p) => `<a class="tache" href="#/project/${p.id}">
            <div class="tache-corps"><div class="tache-nom">${echapper(p.name)}</div>
            <div class="tache-meta">${echapper(p.category || "projet")}</div></div>
            <div class="tache-fin">${badgeStatut(p.status)}</div></a>`
        )
        .join("")}</div>`
    )}

    ${groupe("Tâches", r.tasks, listeTaches(r.tasks))}

    ${groupe(
      "Collaborateurs",
      r.collaborators,
      `<div class="liste-taches">${r.collaborators
        .map(
          (c) => `<a class="collab" href="#/collaborator/${c.id}">
            <span class="avatar">${echapper(initiales(c.name))}</span>
            <div class="tache-corps"><div class="tache-nom">${echapper(c.name)}</div>
            <div class="tache-meta">${echapper(c.role || "—")}</div></div>
            <div class="tache-fin">${badgeStatut(c.status)}</div></a>`
        )
        .join("")}</div>`
    )}

    ${r.total === 0 ? `<p class="vide">Rien trouvé.</p>` : ""}`;
}

/* =====================================================
   Métadonnées des formulaires
   ===================================================== */

let META = null;

async function meta() {
  if (!META) META = await api("/api/meta");
  return META;
}

function oublierMeta() {
  META = null;
}

/* =====================================================
   Modale générique
   =====================================================
   Un seul squelette dans le HTML, rempli à la demande. La promesse
   se résout avec les valeurs du formulaire, ou null si l'utilisateur
   annule.
   ===================================================== */

const modaleFond = $("#modale-fond");
const modaleTitre = $("#modale-titre");
const modaleCorps = $("#modale-corps");
const modaleForm = $("#modale-form");
const modaleValider = $("#modale-valider");

let resoudreModale = null;

function fermerModale(valeur = null) {
  modaleFond.hidden = true;
  modaleCorps.innerHTML = "";
  if (resoudreModale) {
    const resoudre = resoudreModale;
    resoudreModale = null;
    resoudre(valeur);
  }
}

function ouvrirModale({ titre, champs, valider = "Créer" }) {
  modaleTitre.textContent = titre;
  modaleValider.textContent = valider;

  modaleCorps.innerHTML = champs
    .map((champ) => rendreChamp(champ))
    .join("");

  modaleFond.hidden = false;

  const premier = modaleCorps.querySelector("input, select, textarea");
  if (premier) setTimeout(() => premier.focus(), 40);

  return new Promise((resoudre) => {
    resoudreModale = resoudre;
  });
}

function rendreChamp(champ) {
  const { nom, libelle, type = "text", valeur = "", options, requis, placeholder = "", demi } = champ;

  const corps = (() => {
    if (type === "select") {
      return `<select name="${nom}">${options
        .map(
          (option) => {
            const [v, l] = Array.isArray(option) ? option : [option, option];
            return `<option value="${echapper(v)}" ${v === valeur ? "selected" : ""}>${echapper(l)}</option>`;
          }
        )
        .join("")}</select>`;
    }
    if (type === "textarea") {
      return `<textarea name="${nom}" placeholder="${echapper(placeholder)}">${echapper(valeur)}</textarea>`;
    }
    return `<input type="${type}" name="${nom}" value="${echapper(valeur)}"
              placeholder="${echapper(placeholder)}" ${requis ? "required" : ""}>`;
  })();

  return `<div class="champ" ${demi ? 'style="margin-bottom:15px"' : ""}>
    <label for="${nom}">${echapper(libelle)}${requis ? " *" : ""}</label>
    ${corps}
  </div>`;
}

modaleForm.addEventListener("submit", (evenement) => {
  evenement.preventDefault();

  const donnees = {};
  new FormData(modaleForm).forEach((valeur, cle) => {
    donnees[cle] = typeof valeur === "string" ? valeur.trim() : valeur;
  });

  fermerModale(donnees);
});

$("#modale-fermer").addEventListener("click", () => fermerModale(null));
$("#modale-annuler").addEventListener("click", () => fermerModale(null));

modaleFond.addEventListener("click", (evenement) => {
  if (evenement.target === modaleFond) fermerModale(null);
});

/* =====================================================
   Formulaires métier
   ===================================================== */

async function nouvelleTache(projetPreRempli = "", collabPreRempli = "") {
  const m = await meta();

  const projets = ["", ...new Set([...m.projets, ...m.projets_cites])].filter(
    (valeur, index, tout) => index === tout.indexOf(valeur)
  );

  const donnees = await ouvrirModale({
    titre: "Nouvelle tâche",
    valider: "Créer la tâche",
    champs: [
      { nom: "title", libelle: "Nom", requis: true, placeholder: "Finir la phase 1" },
      { nom: "priority", libelle: "Priorité", type: "select", valeur: "medium", options: m.priorites },
      { nom: "status", libelle: "Statut", type: "select", valeur: "active", options: m.statuts },
      { nom: "platform", libelle: "Plateforme", type: "select", valeur: "Autre", options: m.plateformes },
      {
        nom: "project",
        libelle: "Projet",
        type: "select",
        valeur: projetPreRempli,
        options: projets.map((p) => [p, p || "— Aucun —"]),
      },
      { nom: "collaborator", libelle: "Collaborateur", valeur: collabPreRempli || "Moi" },
      { nom: "deadline", libelle: "Délai", type: "select", valeur: "7j", options: m.delais },
      { nom: "objectif", libelle: "Objectif", type: "textarea", placeholder: "Ce qui doit être accompli." },
    ],
  });

  if (!donnees) return null;

  try {
    const tache = await api("/api/tasks", { method: "POST", corps: donnees });
    toast("Tâche créée", tache.name);
    oublierMeta();
    await Promise.all([rendre(), majCompteurs()]);
    return tache;
  } catch (erreur) {
    signalerErreur(erreur, "Création impossible");
    return null;
  }
}

async function nouveauProjet() {
  const m = await meta();

  const donnees = await ouvrirModale({
    titre: "Nouveau projet",
    valider: "Créer le projet",
    champs: [
      { nom: "name", libelle: "Nom", requis: true, placeholder: "AI Video Editor" },
      { nom: "priority", libelle: "Priorité", type: "select", valeur: "medium", options: m.priorites },
      { nom: "status", libelle: "Statut", type: "select", valeur: "active", options: m.statuts },
      { nom: "category", libelle: "Catégorie", placeholder: "software, web, cybersecurity…" },
      { nom: "repository", libelle: "Repository", placeholder: "https://github.com/…" },
    ],
  });

  if (!donnees) return null;

  try {
    const projet = await api("/api/projects", { method: "POST", corps: donnees });
    toast("Projet créé", projet.name);
    oublierMeta();
    await Promise.all([rendre(), majCompteurs()]);
    return projet;
  } catch (erreur) {
    signalerErreur(erreur, "Création impossible");
    return null;
  }
}

async function captureRapide() {
  const donnees = await ouvrirModale({
    titre: "Capture rapide",
    valider: "Déposer dans l'Inbox",
    champs: [
      { nom: "title", libelle: "Quoi ?", requis: true, placeholder: "Une idée à ne pas perdre" },
      { nom: "detail", libelle: "Détail", type: "textarea", placeholder: "Facultatif." },
    ],
  });

  if (!donnees) return null;

  try {
    const tache = await api("/api/tasks/capture", { method: "POST", corps: donnees });
    toast("Déposé dans l'Inbox", tache.name);
    await Promise.all([rendre(), majCompteurs()]);
    return tache;
  } catch (erreur) {
    signalerErreur(erreur, "Capture impossible");
    return null;
  }
}

async function nouveauCollaborateur() {
  const m = await meta();

  const donnees = await ouvrirModale({
    titre: "Nouveau collaborateur",
    valider: "Créer la fiche",
    champs: [
      { nom: "name", libelle: "Nom", requis: true },
      { nom: "status", libelle: "Statut", type: "select", valeur: "active", options: m.statuts_collaborateur },
      { nom: "role", libelle: "Rôle", placeholder: "Developer" },
      { nom: "company", libelle: "Société" },
      { nom: "discord", libelle: "Discord" },
      { nom: "email", libelle: "Email", type: "email" },
      { nom: "github", libelle: "GitHub" },
    ],
  });

  if (!donnees) return null;

  try {
    const fiche = await api("/api/collaborators", { method: "POST", corps: donnees });
    toast("Fiche créée", fiche.name);
    oublierMeta();
    await Promise.all([rendre(), majCompteurs()]);
    return fiche;
  } catch (erreur) {
    signalerErreur(erreur, "Création impossible");
    return null;
  }
}

async function ajouterNote(genre, id, nom) {
  const donnees = await ouvrirModale({
    titre: `Ajouter une note — ${nom}`,
    valider: "Ajouter",
    champs: [
      { nom: "text", libelle: "Note", type: "textarea", requis: true, placeholder: "Ce que tu veux retrouver plus tard." },
    ],
  });

  if (!donnees) return;

  try {
    await api(`/api/${genre}/${id}/notes`, { method: "POST", corps: donnees });
    toast("Note ajoutée", "Elle est sous « Notes » dans la fiche.");
    await rendre();
  } catch (erreur) {
    signalerErreur(erreur, "Note non ajoutée");
  }
}

/* =====================================================
   Archivage
   ===================================================== */

async function archiver(genre, id, nom, version) {
  const libelle = genre === "tasks" ? "cette tâche" : "ce projet";

  const donnees = await ouvrirModale({
    titre: "Archiver",
    valider: "Archiver",
    champs: [
      {
        nom: "confirmation",
        libelle:
          `« ${nom} » passera en statut « archived » et rejoindra le dossier ` +
          `Archives. Le fichier Markdown n'est jamais supprimé. Archiver ${libelle} ?`,
        type: "select",
        valeur: "non",
        options: [["non", "Non, annuler"], ["oui", "Oui, archiver"]],
      },
    ],
  });

  if (!donnees || donnees.confirmation !== "oui") return;

  try {
    const url = `/api/${genre}/${id}` + (version ? `?version=${version}` : "");
    const resultat = await api(url, { method: "DELETE" });
    toast("Archivé", `${resultat.name} → dossier Archives`);
    location.hash = genre === "tasks" ? "#/tasks" : "#/projects";
    await Promise.all([rendre(), majCompteurs()]);
  } catch (erreur) {
    signalerErreur(erreur, "Archivage impossible");
  }
}

/* =====================================================
   Édition inline
   =====================================================
   Un clic sur une propriété la remplace par un champ. La valeur
   part en PATCH à la validation, avec la version de la note pour
   que le serveur détecte une modification faite dans Obsidian.
   ===================================================== */

function brancherEditionInline(genre, id, version) {
  $$("dd.editable").forEach((cellule) => {
    cellule.addEventListener("click", function ouvrir() {
      if (cellule.querySelector("select, input")) return;

      const champ = cellule.dataset.champ;
      const type = cellule.dataset.type || "text";
      const valeur = cellule.dataset.valeur || "";
      const contenuOrigine = cellule.innerHTML;

      const options = cellule.dataset.options
        ? JSON.parse(cellule.dataset.options)
        : null;

      cellule.innerHTML = options
        ? `<select>${options
            .map(
              (option) => {
                const [v, l] = Array.isArray(option) ? option : [option, option];
                return `<option value="${echapper(v)}" ${v === valeur ? "selected" : ""}>${echapper(l)}</option>`;
              }
            )
            .join("")}</select>`
        : `<input type="${type}" value="${echapper(valeur)}">`;

      const saisie = cellule.querySelector("select, input");
      saisie.focus();
      if (saisie.select) saisie.select();

      let termine = false;

      const annuler = () => {
        if (termine) return;
        termine = true;
        cellule.innerHTML = contenuOrigine;
      };

      const enregistrer = async () => {
        if (termine) return;
        termine = true;

        const nouvelle = saisie.value.trim();

        if (nouvelle === valeur) {
          cellule.innerHTML = contenuOrigine;
          return;
        }

        cellule.classList.add("enregistrement");

        try {
          await api(`/api/${genre}/${id}`, {
            method: "PATCH",
            corps: { [champ]: nouvelle, version },
          });
          toast("Enregistré", `${champ} → ${nouvelle || "vide"}`);
          oublierMeta();
          await Promise.all([rendre(), majCompteurs()]);
        } catch (erreur) {
          signalerErreur(erreur, "Modification refusée");
          cellule.classList.remove("enregistrement");
          cellule.innerHTML = contenuOrigine;
        }
      };

      // Permet d'annuler depuis l'extérieur (touche Échap globale)
      // même si le focus a quitté le champ entre-temps.
      cellule._annuler = annuler;

      saisie.addEventListener("blur", enregistrer);
      saisie.addEventListener("change", () => {
        if (options) enregistrer();
      });
      saisie.addEventListener("keydown", (evenement) => {
        if (evenement.key === "Enter") { evenement.preventDefault(); enregistrer(); }
        if (evenement.key === "Escape") { evenement.preventDefault(); annuler(); }
      });
    });
  });
}

/** Fabrique une cellule de propriété éditable. */
function ddEditable(champ, valeur, rendu, options = null, type = "text") {
  const attributs = [
    `class="editable"`,
    `data-champ="${champ}"`,
    `data-valeur="${echapper(valeur ?? "")}"`,
    `data-type="${type}"`,
  ];

  if (options) {
    attributs.push(`data-options='${JSON.stringify(options).replace(/'/g, "&#39;")}'`);
  }

  return `<dd ${attributs.join(" ")}>${rendu}</dd>`;
}

/* =====================================================
   Page Activité (§29)
   =====================================================
   Le fil vient des sections « ## Historique » des notes elles-mêmes.
   Rien n'est stocké à côté : effacer un historique dans Obsidian le
   fait disparaître d'ici, ce qui est le propre d'une vue.
   ===================================================== */

const GENRES_ACTIVITE = {
  statut:   { libelle: "Statuts",    icone: "◆", teinte: "medium" },
  priorite: { libelle: "Priorités",  icone: "▲", teinte: "high" },
  echeance: { libelle: "Échéances",  icone: "◷", teinte: "accent3" },
  champ:    { libelle: "Champs",     icone: "✎", teinte: "accent2" },
  creation: { libelle: "Créations",  icone: "✦", teinte: "low" },
  note:     { libelle: "Notes",      icone: "❝", teinte: "neutre" },
};

// Les routes des fiches sont au singulier (#/task/…), pas au
// pluriel comme les listes : un lien au pluriel ne mène nulle part.
const TYPES_NOTE = { task: "task", project: "project", collaborator: "collaborator" };

let FILTRE_ACTIVITE = "changements";

async function pageActivite() {
  const requete =
    FILTRE_ACTIVITE === "tout"
      ? "/api/activity?limite=300"
      : FILTRE_ACTIVITE === "changements"
        ? "/api/activity?limite=300&changements=true"
        : `/api/activity?limite=300&genre=${FILTRE_ACTIVITE}`;

  const [fil, complet] = await Promise.all([
    api(requete),
    api("/api/activity?limite=1"),
  ]);

  const compteurs = complet.par_genre || {};
  const totalChangements = Object.entries(compteurs)
    .filter(([genre]) => genre !== "note")
    .reduce((somme, [, valeur]) => somme + valeur, 0);

  const onglets = [
    ["changements", `Changements (${totalChangements})`],
    ["tout", `Tout (${Object.values(compteurs).reduce((s, v) => s + v, 0)})`],
    ...Object.entries(GENRES_ACTIVITE)
      .filter(([genre]) => compteurs[genre])
      .map(([genre, info]) => [genre, `${info.libelle} (${compteurs[genre]})`]),
  ];

  // Regroupement par journée, dans l'ordre du fil.
  const jours = [];
  fil.items.forEach((entree) => {
    const dernier = jours[jours.length - 1];
    if (dernier && dernier.date === entree.date) dernier.entrees.push(entree);
    else jours.push({ date: entree.date, entrees: [entree] });
  });

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Activité</h1>
        <p class="page-sous-titre">
          ${fil.total} entrée${fil.total > 1 ? "s" : ""}, lues dans les notes du Vault
        </p>
      </div>
    </div>

    <div class="onglets" style="margin-bottom:18px">
      ${onglets
        .map(
          ([valeur, libelle]) =>
            `<button class="onglet ${FILTRE_ACTIVITE === valeur ? "actif" : ""}"
                     data-activite="${valeur}">${echapper(libelle)}</button>`
        )
        .join("")}
    </div>

    ${
      jours.length
        ? jours.map((jour) => blocJour(jour)).join("")
        : `<p class="vide">Rien à afficher pour ce filtre.</p>`
    }`;
}

function blocJour({ date, entrees }) {
  const quand = new Date(date + "T12:00:00");
  const aujourdhui = new Date();
  aujourdhui.setHours(12, 0, 0, 0);

  const ecart = Math.round((aujourdhui - quand) / 86400000);

  const relatif =
    ecart === 0 ? "Aujourd'hui" : ecart === 1 ? "Hier" : ecart < 7 ? `Il y a ${ecart} jours` : "";

  const libelle = quand.toLocaleDateString("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: quand.getFullYear() === aujourdhui.getFullYear() ? undefined : "numeric",
  });

  return `
    <section class="jour-activite">
      <header class="jour-activite-tete">
        <span class="jour-activite-date">${echapper(libelle)}</span>
        ${relatif ? `<span class="jour-activite-relatif">${relatif}</span>` : ""}
        <span class="jour-activite-compte">${entrees.length}</span>
      </header>
      <div class="fil">
        ${entrees.map((e) => ligneActivite(e)).join("")}
      </div>
    </section>`;
}

function ligneActivite(entree) {
  const info = GENRES_ACTIVITE[entree.genre] || GENRES_ACTIVITE.note;
  const chemin = TYPES_NOTE[entree.type] || "tasks";

  // Les comptes rendus rédigés à la main peuvent faire dix lignes :
  // on les coupe, le texte entier reste dans la note.
  const brut = entree.texte;
  const long = brut.length > 230;
  const texte = long ? brut.slice(0, 230).trimEnd() + "…" : brut;

  return `
    <article class="fil-ligne" style="--teinte: var(--${info.teinte})">
      <span class="fil-heure">${entree.heure || "—"}</span>
      <span class="fil-ico" title="${info.libelle}">${info.icone}</span>
      <div class="fil-corps">
        <div class="fil-texte">${enligne(texte)}</div>
        <a class="fil-note" href="#/${chemin}/${entree.id}">${echapper(entree.note)}</a>
      </div>
    </article>`;
}

function brancherActivite() {
  $$(".onglet[data-activite]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      FILTRE_ACTIVITE = bouton.dataset.activite;
      rendre();
    })
  );
}

/* =====================================================
   Vue Graph (§23)
   =====================================================
   Disposition par forces, écrite à la main : répulsion entre tous
   les nœuds, ressorts sur les liens, rappel vers le centre. Une
   trentaine de nœuds ne justifie pas une bibliothèque.

   La simulation est **déterministe** — positions de départ en
   spirale, aucun tirage au sort. Deux affichages successifs donnent
   le même dessin, ce qui évite de devoir réapprendre la carte à
   chaque visite.
   ===================================================== */

const GRAPH = { largeur: 900, hauteur: 620, terminees: false, survole: null };

function simuler(noeuds, liens, { largeur, hauteur }) {
  const n = noeuds.length;
  if (!n) return [];

  // Départ en spirale : réparti, et surtout reproductible.
  const or = Math.PI * (3 - Math.sqrt(5)); // angle d'or
  const points = noeuds.map((noeud, i) => ({
    ...noeud,
    x: largeur / 2 + Math.cos(i * or) * (18 + i * 9),
    y: hauteur / 2 + Math.sin(i * or) * (18 + i * 9),
    vx: 0,
    vy: 0,
  }));

  const index = new Map(points.map((p) => [p.id, p]));
  const aretes = liens
    .map((l) => ({ a: index.get(l.de), b: index.get(l.vers) }))
    .filter((a) => a.a && a.b);

  const REPULSION = 5200;
  const RESSORT = 0.011;
  const LONGUEUR = 115;
  const CENTRAGE = 0.0016;
  const FROTTEMENT = 0.86;

  for (let tour = 0; tour < 420; tour += 1) {
    // Répulsion : chaque paire se repousse.
    for (let i = 0; i < n; i += 1) {
      for (let j = i + 1; j < n; j += 1) {
        const a = points[i];
        const b = points[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;

        if (d2 < 0.01) { dx = (i - j) * 0.5 || 0.5; dy = 0.5; d2 = 0.5; }

        const d = Math.sqrt(d2);
        const force = REPULSION / d2;
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;

        a.vx -= fx; a.vy -= fy;
        b.vx += fx; b.vy += fy;
      }
    }

    // Ressorts : les nœuds liés se rapprochent.
    aretes.forEach(({ a, b }) => {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 0.5;
      const force = (d - LONGUEUR) * RESSORT;
      const fx = (dx / d) * force;
      const fy = (dy / d) * force;

      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    });

    // Rappel au centre, sinon les nœuds isolés partent à l'infini.
    points.forEach((p) => {
      p.vx += (largeur / 2 - p.x) * CENTRAGE;
      p.vy += (hauteur / 2 - p.y) * CENTRAGE;

      p.vx *= FROTTEMENT;
      p.vy *= FROTTEMENT;
      p.x += p.vx;
      p.y += p.vy;
    });
  }

  // Recadre le dessin sur la zone visible.
  const marge = 54;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);

  const echelle = Math.min(
    (largeur - marge * 2) / Math.max(maxX - minX, 1),
    (hauteur - marge * 2) / Math.max(maxY - minY, 1),
    1.5
  );

  points.forEach((p) => {
    p.x = marge + (p.x - minX) * echelle;
    p.y = marge + (p.y - minY) * echelle;
  });

  return points;
}

function teinteNoeud(noeud) {
  if (noeud.type === "project") return "accent";
  if (noeud.type === "collaborator") return "accent2";

  const p = (noeud.priorite || "").toLowerCase();
  return PRIORITES.includes(p) ? p : "neutre";
}

function rayonNoeud(noeud) {
  if (noeud.type === "project") return 13 + Math.min(noeud.poids, 8) * 1.6;
  if (noeud.type === "collaborator") return 11 + Math.min(noeud.poids, 6) * 1.2;
  return 7;
}

async function pageGraph() {
  const donnees = await api(
    `/api/graph${GRAPH.terminees ? "?inclure_terminees=true" : ""}`
  );

  if (!donnees.noeuds.length) {
    return `<div class="page-tete"><div><h1 class="page-titre">Graph</h1></div></div>
            <p class="vide">Aucune note à relier.</p>`;
  }

  const points = simuler(donnees.noeuds, donnees.liens, GRAPH);
  const index = new Map(points.map((p) => [p.id, p]));

  const aretes = donnees.liens
    .map((l) => ({ a: index.get(l.de), b: index.get(l.vers), genre: l.genre }))
    .filter((a) => a.a && a.b);

  const isoles = new Set(donnees.isoles);

  const compte = (type) => donnees.noeuds.filter((n) => n.type === type).length;

  return `
    <div class="page-tete">
      <div>
        <h1 class="page-titre">Graph</h1>
        <p class="page-sous-titre">
          ${compte("project")} projets · ${compte("task")} tâches ·
          ${compte("collaborator")} collaborateurs ·
          ${aretes.length} lien${aretes.length > 1 ? "s" : ""}
        </p>
      </div>
      <button class="btn ${GRAPH.terminees ? "btn-primaire" : ""}" data-graph="terminees">
        ${GRAPH.terminees ? "✓ " : ""}Inclure les terminées
      </button>
    </div>

    <div class="graph-legende">
      <span class="legende-ligne"><span class="legende-pastille" style="background:var(--accent)"></span>Projet</span>
      <span class="legende-ligne"><span class="legende-pastille" style="background:var(--accent2)"></span>Collaborateur</span>
      <span class="legende-ligne"><span class="legende-pastille" style="background:var(--critical)"></span>Tâche (couleur = priorité)</span>
      ${
        isoles.size
          ? `<span class="graph-note">${isoles.size} note${isoles.size > 1 ? "s" : ""} sans relation</span>`
          : ""
      }
    </div>

    <div class="graph-cadre">
      <svg id="graph-svg" viewBox="0 0 ${GRAPH.largeur} ${GRAPH.hauteur}"
           preserveAspectRatio="xMidYMid meet">
        <g id="graph-camera">
          ${aretes
            .map(
              (a) => `<line class="arete arete-${a.genre}"
                        data-de="${a.a.id}" data-vers="${a.b.id}"
                        x1="${a.a.x.toFixed(1)}" y1="${a.a.y.toFixed(1)}"
                        x2="${a.b.x.toFixed(1)}" y2="${a.b.y.toFixed(1)}"></line>`
            )
            .join("")}
          ${points
            .map((p) => {
              const r = rayonNoeud(p);
              const etiquette = p.nom.length > 26 ? p.nom.slice(0, 25) + "…" : p.nom;
              return `<g class="noeud noeud-${p.type} ${isoles.has(p.id) ? "isole" : ""}"
                         data-id="${p.id}" data-type="${p.type}"
                         style="--teinte: var(--${teinteNoeud(p)})"
                         transform="translate(${p.x.toFixed(1)},${p.y.toFixed(1)})">
                        <circle class="halo" r="${r + 7}"></circle>
                        <circle class="rond" r="${r}"></circle>
                        <text class="etiquette" y="${r + 15}">${echapper(etiquette)}</text>
                        <title>${echapper(p.nom)}${p.poids ? ` — ${p.poids} lien(s)` : ""}</title>
                      </g>`;
            })
            .join("")}
        </g>
      </svg>
    </div>

    <p class="graph-aide">
      Survoler un nœud éclaire ses voisins · cliquer ouvre la fiche ·
      molette pour zoomer, glisser pour déplacer
    </p>`;
}

function brancherGraph() {
  const svg = $("#graph-svg");
  if (!svg) return;

  $$("[data-graph]").forEach((bouton) =>
    bouton.addEventListener("click", () => {
      GRAPH.terminees = !GRAPH.terminees;
      rendre();
    })
  );

  const camera = $("#graph-camera");
  const aretes = $$(".arete", svg);
  const noeuds = $$(".noeud", svg);

  // Voisinage, calculé une fois.
  const voisins = new Map();
  aretes.forEach((arete) => {
    const { de, vers } = arete.dataset;
    if (!voisins.has(de)) voisins.set(de, new Set());
    if (!voisins.has(vers)) voisins.set(vers, new Set());
    voisins.get(de).add(vers);
    voisins.get(vers).add(de);
  });

  noeuds.forEach((noeud) => {
    const id = noeud.dataset.id;

    noeud.addEventListener("mouseenter", () => {
      const proches = voisins.get(id) || new Set();
      svg.classList.add("focalise");

      noeuds.forEach((autre) =>
        autre.classList.toggle(
          "eclaire",
          autre.dataset.id === id || proches.has(autre.dataset.id)
        )
      );

      aretes.forEach((arete) =>
        arete.classList.toggle(
          "eclaire",
          arete.dataset.de === id || arete.dataset.vers === id
        )
      );
    });

    noeud.addEventListener("mouseleave", () => {
      svg.classList.remove("focalise");
      noeuds.forEach((a) => a.classList.remove("eclaire"));
      aretes.forEach((a) => a.classList.remove("eclaire"));
    });

    noeud.addEventListener("click", () => {
      const chemin = TYPES_NOTE[noeud.dataset.type] || "task";
      location.hash = `#/${chemin}/${id}`;
    });
  });

  /* Zoom et déplacement — transformation appliquée au groupe, les
     coordonnées des nœuds ne changent jamais. */
  const vue = { x: 0, y: 0, echelle: 1 };

  const appliquer = () =>
    camera.setAttribute(
      "transform",
      `translate(${vue.x},${vue.y}) scale(${vue.echelle})`
    );

  svg.addEventListener(
    "wheel",
    (evenement) => {
      evenement.preventDefault();
      const facteur = evenement.deltaY < 0 ? 1.12 : 1 / 1.12;
      const avant = vue.echelle;
      vue.echelle = Math.min(3.5, Math.max(0.4, vue.echelle * facteur));

      // Zoome vers le pointeur plutôt que vers le coin.
      const rect = svg.getBoundingClientRect();
      const px = ((evenement.clientX - rect.left) / rect.width) * GRAPH.largeur;
      const py = ((evenement.clientY - rect.top) / rect.height) * GRAPH.hauteur;

      vue.x = px - ((px - vue.x) / avant) * vue.echelle;
      vue.y = py - ((py - vue.y) / avant) * vue.echelle;
      appliquer();
    },
    { passive: false }
  );

  let glisse = null;

  svg.addEventListener("pointerdown", (evenement) => {
    if (evenement.target.closest(".noeud")) return;
    glisse = { x: evenement.clientX, y: evenement.clientY, vx: vue.x, vy: vue.y };
    svg.classList.add("deplace");
    svg.setPointerCapture(evenement.pointerId);
  });

  svg.addEventListener("pointermove", (evenement) => {
    if (!glisse) return;
    const rect = svg.getBoundingClientRect();
    const ratio = GRAPH.largeur / rect.width;
    vue.x = glisse.vx + (evenement.clientX - glisse.x) * ratio;
    vue.y = glisse.vy + (evenement.clientY - glisse.y) * ratio;
    appliquer();
  });

  const relacher = () => { glisse = null; svg.classList.remove("deplace"); };
  svg.addEventListener("pointerup", relacher);
  svg.addEventListener("pointercancel", relacher);
}

/* =====================================================
   Routage
   ===================================================== */

const ROUTES = [
  [/^\/?$/,                      () => pageDashboard()],
  [/^\/dashboard$/,              () => pageDashboard()],
  [/^\/inbox$/,                  () => pageInbox()],
  [/^\/tasks$/,                  () => pageTaches()],
  [/^\/task\/(.+)$/,             (m) => pageTache(m[1])],
  [/^\/projects$/,               () => pageProjets()],
  [/^\/project\/(.+)$/,          (m) => pageProjet(m[1])],
  [/^\/collaborators$/,          () => pageCollaborateurs()],
  [/^\/collaborator\/(.+)$/,     (m) => pageCollaborateur(m[1])],
  [/^\/activity$/,               () => pageActivite()],
  [/^\/graph$/,                  () => pageGraph()],
  [/^\/search\/?(.*)$/,          (m) => pageRecherche(decodeURIComponent(m[1] || ""))],
];

function cheminCourant() {
  return location.hash.replace(/^#/, "") || "/dashboard";
}

async function rendre() {
  const chemin = cheminCourant();

  for (const [motif, action] of ROUTES) {
    const trouve = chemin.match(motif);
    if (!trouve) continue;

    contenu.innerHTML = `<div class="chargement">Lecture du Vault…</div>`;

    try {
      contenu.innerHTML = await action(trouve);
    } catch (erreur) {
      contenu.innerHTML = `<div class="erreur"><strong>Impossible de lire le Vault.</strong><br>${echapper(erreur.message)}</div>`;
      console.error(erreur);
    }

    brancherFiltresTaches();
    brancherFiltresProjets();
    brancherKanban();
    brancherCalendrier();
    brancherActivite();
    brancherGraph();
    brancherActions();
    majNavigation(chemin);
    return;
  }

  contenu.innerHTML = `<p class="vide">Page inconnue : ${echapper(chemin)}</p>`;
}

/* =====================================================
   Actions des pages
   ===================================================== */

function brancherActions() {
  // Édition inline : la liste de propriétés porte le contexte.
  const proprietes = $(".proprietes[data-genre]");

  if (proprietes) {
    brancherEditionInline(
      proprietes.dataset.genre,
      proprietes.dataset.id,
      Number(proprietes.dataset.version)
    );
  }

  $$("[data-action]", contenu).forEach((bouton) => {
    const { action, genre, id, nom, version, statut, projet } = bouton.dataset;

    bouton.addEventListener("click", async () => {
      if (action === "archiver") {
        await archiver(genre, id, nom, version);
        return;
      }

      if (action === "note") {
        await ajouterNote(genre, id, nom);
        return;
      }

      if (action === "nouvelle-tache-projet") {
        await nouvelleTache(projet);
        return;
      }

      if (action === "nouvelle-tache-collab") {
        await nouvelleTache("", bouton.dataset.collab);
        return;
      }

      if (action === "nouvelle-tache-page") { await nouvelleTache(); return; }
      if (action === "nouveau-projet-page") { await nouveauProjet(); return; }
      if (action === "nouveau-collab-page") { await nouveauCollaborateur(); return; }
      if (action === "capture-page") { await captureRapide(); return; }

      if (action === "statut-suivant") {
        bouton.disabled = true;
        try {
          const resultat = await api(`/api/tasks/${id}`, {
            method: "PATCH",
            corps: { status: statut, version: Number(version) },
          });
          toast("Statut modifié", `→ ${statut} · dossier ${resultat.folder}`);
          // Le fichier a été déplacé : son identifiant a changé.
          location.hash = `#/task/${resultat.id}`;
          await Promise.all([rendre(), majCompteurs()]);
        } catch (erreur) {
          signalerErreur(erreur, "Changement de statut refusé");
          bouton.disabled = false;
        }
      }
    });
  });
}

/* Actions rapides de la barre latérale : hors du contenu, branchées
   une seule fois au démarrage. */
$$(".actions-rapides [data-action]").forEach((bouton) =>
  bouton.addEventListener("click", () => {
    const actions = {
      "nouvelle-tache": () => nouvelleTache(),
      "nouveau-projet": nouveauProjet,
      capture: captureRapide,
    };
    actions[bouton.dataset.action]?.();
  })
);

function majNavigation(chemin) {
  $$(".nav-lien").forEach((lien) => {
    const cible = lien.getAttribute("href").replace(/^#/, "");
    const actif = chemin === cible || (cible !== "/dashboard" && chemin.startsWith(cible.replace(/s$/, "")));
    lien.classList.toggle("actif", chemin === cible || chemin.startsWith(cible + "/"));
  });
}

/* =====================================================
   Compteurs de la sidebar & pied de page
   ===================================================== */

async function majCompteurs() {
  try {
    const [dashboard, sante] = await Promise.all([
      api("/api/dashboard"),
      api("/api/health"),
    ]);

    const taches = await api("/api/tasks");
    const inbox = taches.items.filter((t) => t.is_inbox).length;

    $('[data-compteur="taches"]').textContent = dashboard.compteurs.taches_ouvertes || "";
    $('[data-compteur="projets"]').textContent = dashboard.compteurs.projets_actifs || "";
    $('[data-compteur="inbox"]').textContent = inbox || "";

    $("#pied-info").textContent = `${sante.notes} notes`;
    $("#pied-info").title = sante.vault;
  } catch (erreur) {
    $("#pied-info").textContent = "Vault illisible";
    console.error(erreur);
  }
}

/* =====================================================
   Palette de commandes (Ctrl+K)
   ===================================================== */

const paletteFond = $("#palette-fond");
const paletteChamp = $("#palette-champ");
const paletteResultats = $("#palette-resultats");

function ouvrirPalette() {
  paletteFond.hidden = false;
  paletteChamp.value = "";
  paletteResultats.innerHTML = `<p class="palette-vide">Tape pour chercher dans le Vault.</p>`;
  paletteChamp.focus();
}

function fermerPalette() {
  paletteFond.hidden = true;
}

let minuteurPalette;

paletteChamp.addEventListener("input", () => {
  clearTimeout(minuteurPalette);
  const requete = paletteChamp.value.trim();

  if (!requete) {
    paletteResultats.innerHTML = `<p class="palette-vide">Tape pour chercher dans le Vault.</p>`;
    return;
  }

  minuteurPalette = setTimeout(async () => {
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(requete)}`);

      const entrees = [
        ...r.projects.map((p) => ({ nom: p.name, type: "Projet", lien: `#/project/${p.id}` })),
        ...r.tasks.map((t) => ({ nom: t.name, type: "Tâche", lien: `#/task/${t.id}` })),
        ...r.collaborators.map((c) => ({ nom: c.name, type: "Collaborateur", lien: `#/collaborator/${c.id}` })),
      ].slice(0, 30);

      paletteResultats.innerHTML = entrees.length
        ? entrees
            .map(
              (e) => `<a class="palette-item" href="${e.lien}">
                 <span>${echapper(e.nom)}</span>
                 <span class="palette-type">${e.type}</span>
               </a>`
            )
            .join("")
        : `<p class="palette-vide">Rien trouvé pour « ${echapper(requete)} ».</p>`;

      $$(".palette-item", paletteResultats).forEach((item) =>
        item.addEventListener("click", fermerPalette)
      );
    } catch (erreur) {
      paletteResultats.innerHTML = `<p class="palette-vide">Recherche impossible.</p>`;
      console.error(erreur);
    }
  }, 160);
});

paletteFond.addEventListener("click", (evenement) => {
  if (evenement.target === paletteFond) fermerPalette();
});

document.addEventListener("keydown", (evenement) => {
  if ((evenement.ctrlKey || evenement.metaKey) && evenement.key.toLowerCase() === "k") {
    evenement.preventDefault();
    paletteFond.hidden ? ouvrirPalette() : fermerPalette();
  }

  // Ctrl+N : nouvelle tâche, l'action la plus fréquente (§10).
  if ((evenement.ctrlKey || evenement.metaKey) && evenement.key.toLowerCase() === "n") {
    evenement.preventDefault();
    if (modaleFond.hidden) nouvelleTache();
  }

  if (evenement.key === "Escape") {
    // La modale d'abord : c'est elle qui est au-dessus.
    if (!modaleFond.hidden) {
      fermerModale(null);
      return;
    }

    // Puis une édition inline restée ouverte — le champ peut avoir
    // perdu le focus, il ne recevrait alors pas la touche lui-même.
    const enEdition = $("dd.editable select, dd.editable input");

    if (enEdition) {
      enEdition.closest("dd")?._annuler?.();
      return;
    }

    fermerPalette();
  }
});

/* =====================================================
   Recherche de la barre du haut
   ===================================================== */

const champRecherche = $("#recherche-topbar");
let minuteurRecherche;

champRecherche.addEventListener("input", () => {
  clearTimeout(minuteurRecherche);
  minuteurRecherche = setTimeout(() => {
    const requete = champRecherche.value.trim();
    location.hash = requete ? `#/search/${encodeURIComponent(requete)}` : "#/dashboard";
  }, 260);
});

champRecherche.addEventListener("keydown", (evenement) => {
  if (evenement.key === "Enter") {
    clearTimeout(minuteurRecherche);
    const requete = champRecherche.value.trim();
    if (requete) location.hash = `#/search/${encodeURIComponent(requete)}`;
  }
});

/* =====================================================
   Thème
   ===================================================== */

const bascule = $("#bascule-theme");

function appliquerTheme(theme) {
  document.documentElement.dataset.theme = theme;
  bascule.textContent = theme === "dark" ? "☾" : "☀";
  localStorage.setItem("vault-theme", theme);
}

bascule.addEventListener("click", async () => {
  appliquerTheme(
    document.documentElement.dataset.theme === "dark" ? "light" : "dark"
  );

  // Les `stroke` et `fill` d'un SVG déjà dessiné ne se réévaluent pas
  // quand une variable CSS change : un élément créé après la bascule
  // prend la bonne couleur, un élément existant garde l'ancienne,
  // même après un reflow forcé. Redessiner la page est le seul remède
  // fiable — et il ne coûte rien, les données sont déjà là.
  if ($("svg")) await rendre();
});

appliquerTheme(localStorage.getItem("vault-theme") || "dark");

/* =====================================================
   Actualisation
   ===================================================== */

const boutonActualiser = $("#btn-actualiser");

boutonActualiser.addEventListener("click", async () => {
  boutonActualiser.classList.add("tourne");
  await Promise.all([rendre(), majCompteurs()]);
  setTimeout(() => boutonActualiser.classList.remove("tourne"), 700);
});

/* =====================================================
   Rafraîchissement automatique (§28)
   =====================================================
   Le serveur surveille le Vault et annonce les changements par SSE.
   Une note modifiée dans Obsidian se voit ici sans rien cliquer.

   Deux précautions :

   - nos propres écritures rafraîchissent déjà la vue ; l'événement
     qui suit est ignoré s'il tombe dans la foulée, pour ne pas
     rejouer un rendu inutile ;
   - l'utilisateur en train de remplir une modale ou d'éditer une
     propriété n'est jamais interrompu — le rafraîchissement attend
     qu'il ait terminé.
   ===================================================== */

let flux = null;

/* Notes signalées pendant que l'utilisateur saisissait. Vide = rien
   en attente ; on les accumule pour que le message final dise ce qui
   a réellement bougé, même après plusieurs annonces. */
let notesEnAttente = new Set();

function occupe() {
  // Une modale ouverte, ou une propriété en cours d'édition.
  return !modaleFond.hidden || !!$("dd.editable select, dd.editable input");
}

async function rafraichirDepuisLeVault(notes = []) {
  notes.forEach((note) => notesEnAttente.add(note));

  if (Date.now() - DERNIERE_ECRITURE < 2500) {
    notesEnAttente.clear();
    return;
  }

  if (occupe()) {
    // On ne coupe pas la saisie en cours : on repassera.
    return;
  }

  const touchees = [...notesEnAttente];
  notesEnAttente.clear();

  await Promise.all([rendre(), majCompteurs()]);

  if (!touchees.length) return;

  toast(
    "Vault mis à jour",
    touchees.length === 1
      ? `« ${touchees[0].replace(/\.md$/, "")} » a changé dans Obsidian.`
      : `${touchees.length} notes ont changé dans Obsidian.`,
    "info",
    3200
  );
}

function ecouterLeVault() {
  if (flux) flux.close();

  flux = new EventSource("/api/events");

  flux.addEventListener("message", (evenement) => {
    let donnees;
    try {
      donnees = JSON.parse(evenement.data);
    } catch {
      return;
    }

    if (donnees.type === "vault") rafraichirDepuisLeVault(donnees.notes);
  });

  flux.addEventListener("error", () => {
    // EventSource se reconnecte tout seul ; on ne signale rien pour
    // ne pas inonder l'écran si le serveur redémarre.
    majIndicateurFlux(false);
  });

  flux.addEventListener("open", () => majIndicateurFlux(true));
}

function majIndicateurFlux(connecte) {
  const pied = $("#pied-info");
  if (!pied) return;
  pied.classList.toggle("hors-ligne", !connecte);
  pied.title = connecte
    ? "Le Vault est surveillé : les changements faits dans Obsidian arrivent tout seuls."
    : "Surveillance interrompue — recharge la page, ou utilise ⟳.";
}

/* Quand l'utilisateur a fini sa saisie, on rattrape le
   rafraîchissement qui avait été mis de côté. */
document.addEventListener("click", () => {
  if (notesEnAttente.size && !occupe()) rafraichirDepuisLeVault();
});

/* =====================================================
   Démarrage
   ===================================================== */

window.addEventListener("hashchange", rendre);

rendre();
majCompteurs();
ecouterLeVault();
