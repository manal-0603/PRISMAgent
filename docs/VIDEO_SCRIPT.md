# Script de la vidéo de démonstration (3 minutes maximum)

Une revue complète prend plusieurs heures avec le quota gratuit de Groq (10 h 30 pour la revue de
démonstration) : elle ne peut pas être filmée en direct. La vidéo montre donc deux choses : un point de validation humaine sur une revue
en cours, puis les résultats d'une revue terminée.

## Préparation, avant d'enregistrer

1. Vérifier le quota du jour : `sysrev quota`.
2. Lancer l'interface : `streamlit run app/streamlit_app.py`.
3. Dans la barre latérale, démarrer une nouvelle revue **sans** cocher « Autonomous mode », avec
   une question de votre choix et « Max records screened » à 20. Attendre environ deux minutes :
   la page affiche « Waiting for your review — checkpoint: protocol ».
4. La revue de démonstration terminée est dans le menu « Review » de la barre latérale.
5. Ouvrir un terminal dans le dossier du projet, police agrandie.

## Déroulé

| Temps | À l'écran | Ce qu'il faut dire |
|---|---|---|
| 0:00 – 0:20 | Schéma d'architecture du README | Le système prend une question de recherche et conduit seul une revue systématique PRISMA 2020. Un coordinateur LangGraph distribue le travail à sept agents : planification, stratégie de recherche, récupération, screening, extraction, rédaction, critique. |
| 0:20 – 0:45 | Revue en pause : écran « Checkpoint 1 » | Voici une revue en cours, arrêtée au premier point de validation humaine. Le planificateur a écrit le protocole et l'agent de recherche a testé ses requêtes sur les bases réelles. Je peux approuver, modifier, ou demander une révision. |
| 0:45 – 1:10 | Revue terminée, onglet « Overview » | Sur une revue terminée : la frise montre les douze étapes. En dessous, les chiffres clés, l'entonnoir de sélection des études, le risque de biais et la part de citations vérifiées. |
| 1:10 – 1:35 | Onglet « Screening », déplier les désaccords | Deux modèles différents jouent les deux relecteurs indépendants, un troisième arbitre les désaccords. Chaque décision a sa justification ; l'accord est mesuré par le kappa de Cohen. |
| 1:35 – 2:00 | Onglet « Studies », déplier une étude | Pour chaque étude incluse, le RAG retrouve les passages du texte intégral, l'agent remplit la fiche d'extraction et doit citer la phrase source. Le programme vérifie que chaque citation existe vraiment dans le texte. |
| 2:00 – 2:25 | Onglets « Report » puis « Quality », déplier un problème | Le manuscrit suit la structure PRISMA, avec références, tableaux et diagramme de flux. L'agent critique, sur un autre modèle, vérifie chaque affirmation contre les preuves et liste ce qu'il faut corriger. |
| 2:25 – 2:45 | Onglet « Quality », déplier « Audit trail » | Tout est tracé : chaque action d'agent, chaque requête, chaque décision. |
| 2:45 – 3:00 | Onglet « Quality », déplier « Evaluation », puis tableau du README | Évaluation : exhaustivité PRISMA, accord inter-agents, vérification des citations, et comparaison du screening avec des décisions humaines. |

Sur la revue en pause, ne cliquez pas sur « Approve » si vous ne voulez pas qu'elle continue : elle
consommerait le quota. Filmez l'écran, puis changez de revue dans le menu « Review ».

## Conseils

- Répéter une fois avec un chronomètre : le déroulé tient en 3 minutes à condition de ne pas
  attendre de chargement.
- Zoomer le navigateur à 110 % pour que les tableaux restent lisibles.
- Ne pas montrer le fichier `.env` ni la clé API.
