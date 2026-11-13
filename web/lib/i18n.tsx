"use client";

// Interface language (English / French). Only the interface is translated: what the agents
// write (protocol, rationales, manuscript, critic's issues) stays in the language they wrote it in.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "en" | "fr";

const en = {
  "brand.sub": "PRISMA 2020 reviews",
  "lang.switch": "Interface language",
  "side.new": "New review",
  "side.reviews": "Reviews",
  "side.none": "No review yet",
  "side.quota": "Free quota left",
  "side.quotaTip": "Estimate of the free daily allowance left for each model (it refills continuously).",
  "side.studies": "{n} studies",

  "list.running": "Running",
  "list.waiting": "Waiting for you",
  "list.finished": "Finished",
  "list.error": "Stopped",
  "list.paused": "Not finished",

  "status.waiting": "Waiting for your review",
  "status.finished": "Finished",
  "status.error": "Stopped on an error",
  "status.paused": "Paused",
  "status.starting": "Starting",
  "status.elsewhere": "running in another window",
  "status.quota": "waiting for the model quota",

  "stage.protocol": "Writing the protocol",
  "stage.search_strategy": "Designing the search",
  "stage.retrieval": "Retrieving records",
  "stage.screen_title_abstract": "Screening titles and abstracts",
  "stage.screen_full_text": "Screening full texts",
  "stage.extraction": "Extracting and appraising",
  "stage.synthesis": "Writing the manuscript",
  "stage.critic": "Checking the manuscript",
  "stage.finalize": "Exporting",

  "step.protocol": "Protocol",
  "step.search_strategy": "Search",
  "step.retrieval": "Retrieval",
  "step.screen_title_abstract": "Abstracts",
  "step.screen_full_text": "Full texts",
  "step.extraction": "Extraction",
  "step.synthesis": "Writing",
  "step.critic": "Critic",
  "step.finalize": "Exports",
  "step.review_protocol": "Approve the protocol",
  "step.review_screening": "Check the screening",
  "step.review_report": "Approve the report",
  "step.you": "You",
  "step.humanTip": "Human checkpoint: {name}",
  "step.progress": "Progress of the review",

  "head.started": "Started {date}",
  "head.auto": "Autonomous",
  "head.human": "Human-in-the-loop",
  "head.cap": "up to {n} records screened",
  "head.resume": "Resume",
  "head.pausedNote": "This review stopped before the end. Resume continues from the last completed stage.",
  "head.cannotOpen": "This review cannot be opened",

  "tab.overview": "Overview",
  "tab.protocol": "Protocol",
  "tab.screening": "Screening",
  "tab.studies": "Studies",
  "tab.report": "Report",
  "tab.quality": "Quality",

  "home.apiDown": "The API is not running",
  "home.apiHint": "Start the interface from the project folder with:",
  "home.title": "Start your first systematic review",
  "home.text":
    "Ask a research question. The agents write the protocol, search the literature, screen, extract, appraise and draft a PRISMA 2020 manuscript.",

  "new.title": "New review",
  "new.sub": "One research question is enough. You approve the protocol before anything is searched.",
  "new.question": "Research question",
  "new.placeholder": "e.g. Does remote monitoring reduce readmissions in adults with heart failure?",
  "new.auto": "Autonomous mode",
  "new.autoHint": "Skip the three human checkpoints. The report will say that no human verified it.",
  "new.more": "More options",
  "new.less": "Hide options",
  "new.perSource": "Records per database",
  "new.screened": "Records screened",
  "new.rounds": "Revision rounds",
  "new.fallback": "If no open full text",
  "new.fallbackAbstract": "Assess on the abstract",
  "new.fallbackExclude": "Report as not retrieved",
  "new.hint": "On the free tier, 24 records screened and 1 revision round fit in one day of quota.",
  "new.cancel": "Cancel",
  "new.start": "Start review",

  "cp.head": "Checkpoint {n} of 3 · {title}",
  "cp1.title": "Approve the protocol",
  "cp1.text":
    "The Planner wrote the protocol and the Search agent tested its queries on the live databases. Read them in the Protocol tab below, then decide. Nothing is retrieved before you approve.",
  "cp.approve": "Approve",
  "cp1.changes": "Request changes",
  "cp1.edit": "Edit it myself",
  "cp1.changesPlaceholder": "e.g. Restrict to adults; add terms for telemonitoring",
  "cp1.send": "Send to the Planner",
  "cp1.save": "Save my edits and continue",
  "cp1.invalid": "Invalid JSON: {error}",
  "cp2.title": "Check the screening decisions",
  "cp2.text":
    "Two reviewers screened {n} records on title and abstract. Change any decision, then approve. Your changes are logged and reported in the manuscript.",
  "cp2.disputed": "Retained and disputed ({n})",
  "cp2.all": "All ({n})",
  "cp2.reviewers": "Reviewers",
  "cp2.settledBy": "settled by {who}",
  "cp2.include": "Include",
  "cp2.exclude": "Exclude",
  "cp2.changed": "changed by you",
  "cp2.approveWith": "Approve with {changes}",
  "cp3.title": "Approve the manuscript",
  "cp3.issues": "The Critic leaves {issues} open: they are listed in the Quality tab below, and the draft is in the Report tab.",
  "cp3.clean": "The Critic found no open issue. The draft is in the Report tab below.",
  "cp3.then": "Approve to export the final files, or ask the Writing agent for a revision.",
  "cp3.approve": "Approve and export",
  "cp3.revise": "Request a revision",
  "cp3.placeholder": "What should the Writing agent change?",
  "cp3.send": "Send to the Writing agent",

  "ov.empty": "The overview fills in as soon as the first records are retrieved.",
  "ov.identified": "Records identified",
  "ov.screened": "Screened",
  "ov.byTwo": "by two reviewers",
  "ov.included": "Studies included",
  "ov.agreement": "Reviewer agreement",
  "ov.selection": "Study selection",
  "ov.hover": "hover a bar for details",
  "ov.f.identified": "Identified",
  "ov.f.unique": "After de-duplication",
  "ov.f.screened": "Screened",
  "ov.f.sought": "Sought in full text",
  "ov.f.assessed": "Assessed",
  "ov.f.included": "Included",
  "ov.tip.duplicates": "{n} duplicates merged",
  "ov.tip.cap": "{n} records below the relevance cap were not screened",
  "ov.tip.excluded": "{n} records excluded on title and abstract",
  "ov.tip.abstract": "{n} assessed on the abstract only",
  "ov.tip.reasons": "{n} reports excluded with reasons",
  "ov.glance": "Quality at a glance",
  "ov.glanceEmpty": "Available after extraction.",
  "ov.rob": "Risk of bias",
  "ov.quotes": "Quotations found in the source",
  "ov.critic": "Critic",
  "ov.noIssue": "No open issue",
  "ov.themes": "Themes of the synthesis",
  "ov.themeStudies": "Studies in this theme",
  "ov.certainty": "Certainty: {level}",
  "ov.prisma": "PRISMA 2020 flow diagram",

  "pr.empty": "The Planner agent has not written the protocol yet.",
  "pr.include": "Include",
  "pr.exclude": "Exclude",
  "pr.fullText": "full text",
  "pr.fullTextTip": "Can only be judged on the full text",
  "pr.strategy": "Search strategy",
  "pr.strategyExtra": "{dbs} · {hits} hits",
  "pr.concept": "Concept {i}",
  "pr.hits": "{n} hits",
  "pr.tested": "The agent tested {n} queries on the live databases before settling on these.",
  "pr.data": "Data to extract and planned methods",
  "pr.outcomes": "Outcomes",
  "pr.designs": "Study designs",
  "pr.synthesis": "Synthesis",
  "pr.briefs": "Briefs from the coordinator to the agents",

  "sc.empty": "No screening decision yet.",
  "sc.ta": "Title and abstract",
  "sc.ft": "Full text",
  "sc.all": "All",
  "sc.included": "Included",
  "sc.excluded": "Excluded",
  "sc.conflicts": "Disagreements",
  "sc.assessed": "Assessed",
  "sc.settled": "{conflicts} settled",
  "sc.record": "Record",
  "sc.decision": "Decision",
  "sc.reviewerA": "Reviewer A",
  "sc.reviewerB": "Reviewer B",
  "sc.agreed": "both reviewers agreed",
  "sc.settledBy": "settled by {who}",
  "sc.reason": "Reason: {reason}",
  "sc.none": "No record in this view.",
  "sc.hint": "Click a record to read why it was included or excluded.",
  "who.adjudicator": "the adjudicator",
  "who.human": "a human reviewer",

  "st.empty": "No study has been extracted yet.",
  "st.rob": "Risk of bias: {level}",
  "st.quotes": "{found}/{checked} quotations found",
  "st.abstractOnly": "abstract only",
  "st.source": "source",
  "st.findings": "Key findings",
  "st.data": "Extracted data",
  "st.found": "found in source",
  "st.notFound": "not found as written",

  "rp.empty": "The manuscript appears here once the Writing agent has produced a draft.",
  "rp.words": "{n} words",
  "rp.final": "final version",
  "rp.draft": "draft under review",
  "rp.evidence": "Evidence table",
  "rp.failed": "The manuscript could not be loaded.",
  "rp.language": "",

  "qa.empty": "The Critic agent reviews the manuscript once a draft exists.",
  "qa.open": "Open issues",
  "qa.openNote": "{major} major · after {rounds}",
  "qa.quotes": "Quotations found",
  "qa.quotesNote": "{found} of {checked} in the sources",
  "qa.prisma": "PRISMA items",
  "qa.reported": "reported",
  "qa.invented": "Invented citations",
  "qa.inventedNote": "references to unknown records",
  "qa.none": "The critic found no issue.",
  "qa.fix": "Suggested fix",
  "qa.evaluation": "Evaluation",
  "qa.evaluationExtra": "completeness · accuracy · consistency · time",
  "qa.compute": "Compute the evaluation",
  "qa.completeness": "Completeness",
  "qa.consistency": "Inter-agent consistency",
  "qa.accuracy": "Accuracy and grounding",
  "qa.time": "Machine time per stage",
  "qa.timeExtra": "{hours} h · about {manual} person-hours by hand",
  "qa.timeNote":
    "Pipeline time is machine wall-clock time, dominated by API rate limits; it excludes human checkpoint time. Manual figures are estimates from config/manual_effort.yaml, not measurements.",
  "qa.audit": "Audit trail",
  "qa.allAgents": "All agents",
  "qa.trace": "full prompts and answers are in llm_trace.jsonl",
  "qa.colTime": "Time",
  "qa.colAgent": "Agent",
  "qa.colAction": "Action",
  "qa.colDetails": "Details",

  yes: "yes",
  no: "no",
};

type Key = keyof typeof en;

const fr: Record<Key, string> = {
  "brand.sub": "Revues PRISMA 2020",
  "lang.switch": "Langue de l'interface",
  "side.new": "Nouvelle revue",
  "side.reviews": "Revues",
  "side.none": "Aucune revue pour l'instant",
  "side.quota": "Quota gratuit restant",
  "side.quotaTip": "Estimation du quota gratuit journalier restant pour chaque modèle (il se recharge en continu).",
  "side.studies": "{n} études",

  "list.running": "En cours",
  "list.waiting": "À valider",
  "list.finished": "Terminée",
  "list.error": "Arrêtée",
  "list.paused": "Inachevée",

  "status.waiting": "En attente de votre validation",
  "status.finished": "Terminée",
  "status.error": "Arrêtée sur une erreur",
  "status.paused": "En pause",
  "status.starting": "Démarrage",
  "status.elsewhere": "en cours dans une autre fenêtre",
  "status.quota": "en attente du quota du modèle",

  "stage.protocol": "Rédaction du protocole",
  "stage.search_strategy": "Conception de la recherche",
  "stage.retrieval": "Collecte des références",
  "stage.screen_title_abstract": "Tri sur titres et résumés",
  "stage.screen_full_text": "Tri sur textes intégraux",
  "stage.extraction": "Extraction et évaluation",
  "stage.synthesis": "Rédaction du manuscrit",
  "stage.critic": "Vérification du manuscrit",
  "stage.finalize": "Export",

  "step.protocol": "Protocole",
  "step.search_strategy": "Recherche",
  "step.retrieval": "Collecte",
  "step.screen_title_abstract": "Résumés",
  "step.screen_full_text": "Textes",
  "step.extraction": "Extraction",
  "step.synthesis": "Rédaction",
  "step.critic": "Critique",
  "step.finalize": "Exports",
  "step.review_protocol": "Valider le protocole",
  "step.review_screening": "Vérifier le tri",
  "step.review_report": "Valider le rapport",
  "step.you": "Vous",
  "step.humanTip": "Validation humaine : {name}",
  "step.progress": "Avancement de la revue",

  "head.started": "Lancée le {date}",
  "head.auto": "Autonome",
  "head.human": "Avec validation humaine",
  "head.cap": "jusqu'à {n} références triées",
  "head.resume": "Reprendre",
  "head.pausedNote": "Cette revue s'est arrêtée avant la fin. « Reprendre » repart de la dernière étape terminée.",
  "head.cannotOpen": "Impossible d'ouvrir cette revue",

  "tab.overview": "Vue d'ensemble",
  "tab.protocol": "Protocole",
  "tab.screening": "Tri",
  "tab.studies": "Études",
  "tab.report": "Rapport",
  "tab.quality": "Qualité",

  "home.apiDown": "L'API n'est pas démarrée",
  "home.apiHint": "Lancez l'interface depuis le dossier du projet avec :",
  "home.title": "Lancez votre première revue systématique",
  "home.text":
    "Posez une question de recherche. Les agents rédigent le protocole, interrogent la littérature, trient, extraient, évaluent et rédigent un manuscrit PRISMA 2020.",

  "new.title": "Nouvelle revue",
  "new.sub": "Une question de recherche suffit. Vous validez le protocole avant toute recherche.",
  "new.question": "Question de recherche",
  "new.placeholder": "ex. Does remote monitoring reduce readmissions in adults with heart failure?",
  "new.auto": "Mode autonome",
  "new.autoHint": "Passe les trois validations humaines. Le rapport indiquera qu'aucun humain ne l'a vérifié.",
  "new.more": "Plus d'options",
  "new.less": "Masquer les options",
  "new.perSource": "Références par base",
  "new.screened": "Références triées",
  "new.rounds": "Tours de révision",
  "new.fallback": "Sans texte intégral en accès libre",
  "new.fallbackAbstract": "Évaluer sur le résumé",
  "new.fallbackExclude": "Signaler comme non obtenu",
  "new.hint": "Avec le quota gratuit, 24 références triées et 1 tour de révision tiennent en une journée.",
  "new.cancel": "Annuler",
  "new.start": "Lancer la revue",

  "cp.head": "Validation {n} sur 3 · {title}",
  "cp1.title": "Valider le protocole",
  "cp1.text":
    "Le planificateur a rédigé le protocole et l'agent de recherche a testé ses requêtes sur les bases réelles. Lisez-les dans l'onglet Protocole ci-dessous, puis décidez. Rien n'est collecté avant votre validation.",
  "cp.approve": "Valider",
  "cp1.changes": "Demander des changements",
  "cp1.edit": "Modifier moi-même",
  "cp1.changesPlaceholder": "ex. Limiter aux adultes ; ajouter des termes pour la télésurveillance",
  "cp1.send": "Envoyer au planificateur",
  "cp1.save": "Enregistrer mes modifications et continuer",
  "cp1.invalid": "JSON invalide : {error}",
  "cp2.title": "Vérifier les décisions de tri",
  "cp2.text":
    "Deux relecteurs ont trié {n} références sur titre et résumé. Modifiez les décisions si besoin, puis validez. Vos modifications sont journalisées et signalées dans le manuscrit.",
  "cp2.disputed": "Retenues et contestées ({n})",
  "cp2.all": "Toutes ({n})",
  "cp2.reviewers": "Relecteurs",
  "cp2.settledBy": "tranché par {who}",
  "cp2.include": "Inclure",
  "cp2.exclude": "Exclure",
  "cp2.changed": "modifiée par vous",
  "cp2.approveWith": "Valider avec {changes}",
  "cp3.title": "Valider le manuscrit",
  "cp3.issues":
    "Le critique laisse {issues} : ils sont listés dans l'onglet Qualité ci-dessous, et le brouillon est dans l'onglet Rapport.",
  "cp3.clean": "Le critique n'a laissé aucun problème ouvert. Le brouillon est dans l'onglet Rapport ci-dessous.",
  "cp3.then": "Validez pour exporter les fichiers finaux, ou demandez une révision au rédacteur.",
  "cp3.approve": "Valider et exporter",
  "cp3.revise": "Demander une révision",
  "cp3.placeholder": "Que doit changer le rédacteur ?",
  "cp3.send": "Envoyer au rédacteur",

  "ov.empty": "La vue d'ensemble se remplit dès que les premières références sont collectées.",
  "ov.identified": "Références trouvées",
  "ov.screened": "Triées",
  "ov.byTwo": "par deux relecteurs",
  "ov.included": "Études incluses",
  "ov.agreement": "Accord entre relecteurs",
  "ov.selection": "Sélection des études",
  "ov.hover": "survolez une barre pour le détail",
  "ov.f.identified": "Trouvées",
  "ov.f.unique": "Après dédoublonnage",
  "ov.f.screened": "Triées",
  "ov.f.sought": "Texte intégral recherché",
  "ov.f.assessed": "Évaluées",
  "ov.f.included": "Incluses",
  "ov.tip.duplicates": "{n} doublons fusionnés",
  "ov.tip.cap": "{n} références sous le seuil de pertinence n'ont pas été triées",
  "ov.tip.excluded": "{n} références exclues sur titre et résumé",
  "ov.tip.abstract": "{n} évaluées sur le résumé seul",
  "ov.tip.reasons": "{n} rapports exclus avec motif",
  "ov.glance": "Qualité en bref",
  "ov.glanceEmpty": "Disponible après l'extraction.",
  "ov.rob": "Risque de biais",
  "ov.quotes": "Citations retrouvées dans la source",
  "ov.critic": "Critique",
  "ov.noIssue": "Aucun problème ouvert",
  "ov.themes": "Thèmes de la synthèse",
  "ov.themeStudies": "Études dans ce thème",
  "ov.certainty": "Certitude : {level}",
  "ov.prisma": "Diagramme de flux PRISMA 2020",

  "pr.empty": "Le planificateur n'a pas encore rédigé le protocole.",
  "pr.include": "Inclure",
  "pr.exclude": "Exclure",
  "pr.fullText": "texte intégral",
  "pr.fullTextTip": "Ne peut être jugé que sur le texte intégral",
  "pr.strategy": "Stratégie de recherche",
  "pr.strategyExtra": "{dbs} · {hits} résultats",
  "pr.concept": "Concept {i}",
  "pr.hits": "{n} résultats",
  "pr.tested": "L'agent a testé {n} requêtes sur les bases réelles avant de retenir celles-ci.",
  "pr.data": "Données à extraire et méthodes prévues",
  "pr.outcomes": "Critères de jugement",
  "pr.designs": "Types d'études",
  "pr.synthesis": "Synthèse",
  "pr.briefs": "Consignes du coordinateur aux agents",

  "sc.empty": "Aucune décision de tri pour l'instant.",
  "sc.ta": "Titre et résumé",
  "sc.ft": "Texte intégral",
  "sc.all": "Toutes",
  "sc.included": "Incluses",
  "sc.excluded": "Exclues",
  "sc.conflicts": "Désaccords",
  "sc.assessed": "Évaluées",
  "sc.settled": "{conflicts} tranchés",
  "sc.record": "Référence",
  "sc.decision": "Décision",
  "sc.reviewerA": "Relecteur A",
  "sc.reviewerB": "Relecteur B",
  "sc.agreed": "les deux relecteurs sont d'accord",
  "sc.settledBy": "tranchée par {who}",
  "sc.reason": "Motif : {reason}",
  "sc.none": "Aucune référence dans cette vue.",
  "sc.hint": "Cliquez sur une référence pour lire pourquoi elle a été incluse ou exclue.",
  "who.adjudicator": "l'arbitre",
  "who.human": "un relecteur humain",

  "st.empty": "Aucune étude n'a encore été extraite.",
  "st.rob": "Risque de biais : {level}",
  "st.quotes": "{found}/{checked} citations retrouvées",
  "st.abstractOnly": "résumé seul",
  "st.source": "source",
  "st.findings": "Résultats clés",
  "st.data": "Données extraites",
  "st.found": "retrouvée dans la source",
  "st.notFound": "non retrouvée telle quelle",

  "rp.empty": "Le manuscrit apparaît ici dès que le rédacteur a produit un brouillon.",
  "rp.words": "{n} mots",
  "rp.final": "version finale",
  "rp.draft": "brouillon en cours de relecture",
  "rp.evidence": "Tableau des preuves",
  "rp.failed": "Le manuscrit n'a pas pu être chargé.",
  "rp.language": "Le manuscrit et les textes produits par les agents restent en anglais.",

  "qa.empty": "Le critique relit le manuscrit dès qu'un brouillon existe.",
  "qa.open": "Problèmes ouverts",
  "qa.openNote": "{major} majeurs · après {rounds}",
  "qa.quotes": "Citations retrouvées",
  "qa.quotesNote": "{found} sur {checked} dans les sources",
  "qa.prisma": "Éléments PRISMA",
  "qa.reported": "rapportés",
  "qa.invented": "Citations inventées",
  "qa.inventedNote": "renvois à des références inconnues",
  "qa.none": "Le critique n'a trouvé aucun problème.",
  "qa.fix": "Correction proposée",
  "qa.evaluation": "Évaluation",
  "qa.evaluationExtra": "exhaustivité · exactitude · cohérence · temps",
  "qa.compute": "Calculer l'évaluation",
  "qa.completeness": "Exhaustivité",
  "qa.consistency": "Cohérence entre agents",
  "qa.accuracy": "Exactitude et ancrage",
  "qa.time": "Temps machine par étape",
  "qa.timeExtra": "{hours} h · environ {manual} heures-personne à la main",
  "qa.timeNote":
    "Le temps du pipeline est un temps machine réel, dominé par les limites de débit de l'API ; il exclut le temps des validations humaines. Les chiffres manuels sont des estimations tirées de config/manual_effort.yaml, pas des mesures.",
  "qa.audit": "Journal d'audit",
  "qa.allAgents": "Tous les agents",
  "qa.trace": "les requêtes et réponses complètes sont dans llm_trace.jsonl",
  "qa.colTime": "Heure",
  "qa.colAgent": "Agent",
  "qa.colAction": "Action",
  "qa.colDetails": "Détails",

  yes: "oui",
  no: "non",
};

const DICT: Record<Lang, Record<Key, string>> = { en, fr };

// [singular, plural]
const PLURALS = {
  en: {
    issue: ["issue", "issues"],
    openIssue: ["open issue", "open issues"],
    disagreement: ["disagreement", "disagreements"],
    change: ["change", "changes"],
    round: ["critic round", "critic rounds"],
    event: ["event", "events"],
    database: ["database", "databases"],
    dataItem: ["data item", "data items"],
    agent: ["agent", "agents"],
  },
  fr: {
    issue: ["problème ouvert", "problèmes ouverts"],
    openIssue: ["problème ouvert", "problèmes ouverts"],
    disagreement: ["désaccord", "désaccords"],
    change: ["modification", "modifications"],
    round: ["tour de critique", "tours de critique"],
    event: ["événement", "événements"],
    database: ["base", "bases"],
    dataItem: ["donnée", "données"],
    agent: ["agent", "agents"],
  },
} as const;

type Noun = keyof (typeof PLURALS)["en"];

// Values that come from the pipeline's data and have a fixed vocabulary.
const VALUES: Record<string, string> = {
  include: "inclus",
  exclude: "exclu",
  unsure: "incertain",
  low: "faible",
  "some concerns": "quelques réserves",
  high: "élevé",
  unclear: "incertain",
  moderate: "modéré",
  "very low": "très faible",
  poor: "médiocre",
  slight: "très faible",
  fair: "passable",
  substantial: "fort",
  "almost perfect": "presque parfait",
  critical: "critique",
  major: "majeur",
  minor: "mineur",
  true: "oui",
  false: "non",
};

// Agreement with a feminine noun ("certitude").
const FEMININE: Record<string, string> = { high: "élevée", moderate: "modérée" };

// Measures of `sysrev evaluate`, by their key in evaluation.json.
const MEASURES: Record<string, string> = {
  prisma_items_reported: "Éléments PRISMA rapportés",
  prisma_flow_arithmetic_consistent: "Arithmétique du flux PRISMA cohérente",
  included_studies_with_extraction: "Études incluses avec extraction",
  included_studies_with_risk_of_bias: "Études incluses avec risque de biais",
  data_items_reported_by_studies: "Données rapportées par les études",
  studies_read_from_full_text: "Études lues en texte intégral",
  extraction_quotes_verified_in_source: "Citations retrouvées dans la source",
  extraction_quote_verification_rate: "Taux de citations retrouvées",
  citations_to_unknown_records_final: "Renvois à des références inconnues",
  unsupported_statements_found_by_critic_first_draft: "Affirmations non étayées, premier jet",
  unsupported_statements_found_by_critic_final_draft: "Affirmations non étayées, version finale",
  critic_rounds: "Tours de critique",
  eligibility_audit_flagged_included_studies: "Études incluses signalées par l'audit",
  title_abstract_cohen_kappa: "Kappa de Cohen, titre et résumé",
  title_abstract_interpretation: "Interprétation, titre et résumé",
  title_abstract_raw_agreement: "Accord brut, titre et résumé",
  title_abstract_conflicts: "Désaccords, titre et résumé",
  full_text_cohen_kappa: "Kappa de Cohen, texte intégral",
  full_text_interpretation: "Interprétation, texte intégral",
  full_text_raw_agreement: "Accord brut, texte intégral",
  full_text_conflicts: "Désaccords, texte intégral",
  exclusion_audit_agreement: "Accord de l'audit des exclusions",
  exclusion_audit_sample: "Échantillon de l'audit des exclusions",
};

const prettyKey = (key: string) =>
  key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()).replace("Prisma", "PRISMA").replace("cohen", "Cohen");

type I18n = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** Interface text, with {placeholders} filled from `vars`. */
  t: (key: Key, vars?: Record<string, string | number>) => string;
  /** "3 issues" / "3 problèmes ouverts". */
  n: (noun: Noun, count: number) => string;
  /** A value from the data (include, some concerns, moderate…) in the interface language. */
  v: (value: string | null | undefined, feminine?: boolean) => string;
  /** Label of an evaluation measure. */
  measure: (key: string) => string;
  /** Short date, optionally with the time. */
  date: (iso: string, withTime?: boolean) => string;
  number: (value: number) => string;
};

const I18nContext = createContext<I18n | null>(null);
const STORAGE_KEY = "prismagent.lang";

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  // The saved choice, otherwise the browser's language. Read after mount so that the first
  // render matches the server's.
  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = window.localStorage.getItem(STORAGE_KEY);
    } catch {}
    if (saved === "fr" || saved === "en") setLangState(saved);
    else if (navigator.language?.toLowerCase().startsWith("fr")) setLangState("fr");
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {}
  }, []);

  const value = useMemo<I18n>(() => {
    const locale = lang === "fr" ? "fr-FR" : "en-GB";
    return {
      lang,
      setLang,
      t: (key, vars) => {
        let text = DICT[lang][key] ?? en[key] ?? key;
        if (vars) for (const [name, val] of Object.entries(vars)) text = text.replaceAll(`{${name}}`, String(val));
        return text;
      },
      n: (noun, count) => {
        const singular = lang === "fr" ? count < 2 : count === 1;
        return `${count} ${PLURALS[lang][noun][singular ? 0 : 1]}`;
      },
      v: (value, feminine = false) => {
        if (value === null || value === undefined) return "";
        if (lang !== "fr") return String(value);
        const key = String(value).toLowerCase();
        return (feminine && FEMININE[key]) || VALUES[key] || String(value);
      },
      measure: (key) => (lang === "fr" && MEASURES[key]) || prettyKey(key),
      date: (iso, withTime = false) => {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
        const day = d.toLocaleDateString(locale, { day: "numeric", month: "short" });
        if (!withTime) return day;
        const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
        return lang === "fr" ? `${day} à ${time}` : `${day}, ${time}`;
      },
      number: (value) => value.toLocaleString(locale),
    };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside <LanguageProvider>");
  return value;
}
