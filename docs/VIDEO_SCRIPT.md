# Script de la vidéo de démonstration (3 minutes maximum)

Une revue complète prend 30 à 60 minutes avec le quota gratuit de Groq : elle ne peut pas être
filmée en direct. La vidéo montre donc deux choses : un point de validation humaine sur une revue
en cours, puis les résultats d'une revue terminée.

## Préparation, avant d'enregistrer

1. Vérifier le quota du jour : `sysrev quota`.
2. Lancer l'interface : `streamlit run app/streamlit_app.py`.
3. Dans la barre latérale, démarrer une nouvelle revue **sans** cocher « Autonomous mode », avec
   une question de votre choix et « Max records screened » à 20. Attendre environ deux minutes :
   la page affiche « Waiting for your review — checkpoint: protocol ».
4. Garder sous la main la revue de démonstration terminée (dossier `examples/demo_run/`, ou la
   revue correspondante dans la liste « Review run »).
5. Ouvrir un terminal dans le dossier du projet, police agrandie.

## Déroulé

| Temps | À l'écran | Ce qu'il faut dire |
|---|---|---|
| 0:00 – 0:20 | Schéma d'architecture du README | Le système prend une question de recherche et conduit seul une revue systématique PRISMA 2020. Un coordinateur LangGraph distribue le travail à sept agents : planification, stratégie de recherche, récupération, screening, extraction, rédaction, critique. |
| 0:20 – 0:45 | Interface, onglet « Overview » | Voici une revue terminée. La frise du haut montre les douze étapes, dont trois points de validation humaine. En dessous : 120 articles identifiés, 24 passés au screening, 13 études incluses, et le temps passé par étape. |
| 0:45 – 1:10 | Onglets « Protocol » puis « Search » | Le planificateur a écrit le protocole : question PICO, critères d'inclusion et d'exclusion. L'agent de recherche a écrit une requête par base et l'a testée sur les bases réelles. À cette étape, l'humain peut approuver, modifier ou demander une révision. |
| 1:10 – 1:35 | Onglet « Screening », ouvrir un désaccord | Deux modèles différents jouent les deux relecteurs indépendants, un troisième arbitre les désaccords. Chaque décision a sa justification ; l'accord entre relecteurs est mesuré par le kappa de Cohen. |
| 1:35 – 2:00 | Onglet « Studies », ouvrir une étude | Pour chaque étude incluse, le RAG retrouve les passages du texte intégral, l'agent remplit la fiche d'extraction et doit citer la phrase source. Le programme vérifie que chaque citation existe vraiment dans le texte. Le risque de biais est évalué avec l'outil adapté au type d'étude. |
| 2:00 – 2:25 | Onglets « Report » puis « Quality » | Le manuscrit suit la structure PRISMA, avec références numérotées, tableaux et diagramme de flux. L'agent critique, sur un autre modèle, vérifie chaque affirmation contre les preuves et liste ce qu'il faut corriger. |
| 2:25 – 2:45 | Onglet « Audit trail » | Tout est tracé : chaque action d'agent, chaque requête, chaque décision. |
| 2:45 – 3:00 | Onglet « Evaluation » | Évaluation : exhaustivité PRISMA, accord inter-agents, vérification des citations, temps machine comparé à l'effort manuel estimé. |

Si vous avez une revue en pause au premier point de validation (étape 3 de la préparation), montrez-la
à la place de la ligne 0:45 – 1:10 et cliquez sur « Approve » à l'écran.

## Conseils

- Répéter une fois avec un chronomètre : le déroulé tient en 3 minutes à condition de ne pas
  attendre de chargement.
- Zoomer le navigateur à 110 % pour que les tableaux restent lisibles.
- Ne pas montrer le fichier `.env` ni la clé API.
