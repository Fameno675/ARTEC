# ARTEC — Plateforme de suivi de la qualité des services mobiles (Madagascar)

Projet complet : **backend Django + frontend (templates Bootstrap/JS) + moteur de machine learning**, déjà fusionnés.

## Démarrage rapide (Windows)
1. Installer **Python 3.11 ou 3.12** (python.org, cocher « Add to PATH ») et **PostgreSQL 16**.
2. Créer la base : ouvrir `psql` en administrateur et exécuter `scripts\creer_base.sql` (changer le mot de passe dedans).
3. Double-cliquer **`installer.bat`** : crée l'environnement, installe les dépendances, crée `.env` (renseignez `DB_PASSWORD`, puis relancez), applique les migrations.
4. *(facultatif)* **`demo.bat`** : données FICTIVES + comptes de démonstration + une analyse ML.
5. **`lancer.bat`** : ouvre http://127.0.0.1:8000/

Linux/macOS : `./installer.sh`, puis `python manage.py runserver`. Détails et dépannage : `docs/INSTALL_WINDOWS.md`.

**Comptes** : la démo crée `demo.artec@example.mg`, `demo.orange@example.mg`, `demo.yas@example.mg`, `demo.airtel@example.mg` (mot de passe `Demo-Artec-2026!`, **à ne jamais utiliser en production**). Pour les vrais comptes : `python manage.py createsuperuser`, puis `/gestion/` pour créer l'administrateur ARTEC et un compte par opérateur.

## Qui fait quoi
| Acteur | Accès | Possibilités |
|---|---|---|
| **Visiteur** (sans compte) | `/` | Choisit un opérateur, répond aux sondages (10 critères notés de 0 à 10), consulte les résultats publics. Plusieurs avis possibles (une personne peut avoir 3 SIM) ; anti-spam sans donnée personnelle. |
| **Opérateur** (Orange, Yas, Airtel) | `/operateur/` | Importe ses données (CSV/Excel), suit ses indicateurs, dépose et suit des **réclamations** contre un autre opérateur (avec pièces). N'accède qu'à ses propres données. |
| **ARTEC** | `/artec/` | Tableau de bord comparatif, validation des avis, **analyses ML**, **recommandations réglementaires**, instruction des réclamations et décisions, imports, sources externes (avec provenance), sondages configurables, journal d'audit. |
| **Administrateur technique** | `/gestion/` | Comptes, rôles, opérateurs, critères. |

Les 10 critères (sondages) : internet mobile (vitesse, stabilité, disponibilité), appels (qualité sonore, réussite/stabilité), SMS, tarification, crédit et forfaits, mobile money, service client.

## Chaîne de traitement
`avis (formulaire, import CSV/Excel, source externe)` → validation → **avis acceptés** → **moteur ML** (détecte les réponses atypiques, explique pourquoi) → examen humain des alertes → **recommandations** (félicitations / avertissement / instruction de sanction) → décision d'un agent ARTEC (consignée).

* **Temps réel** : la page *Recommandations* (`/artec/recommandations/`) se recalcule à chaque visite sur une fenêtre glissante (7, 30 ou 90 jours) : seules les données récentes comptent. Pour que le ML suive, planifier `analyser.bat` (Planificateur de tâches Windows, p. ex. toutes les heures) ou `python manage.py run_ml_analysis --last-days 30`.
* **Aucune sanction automatique.** Une recommandation et une alerte ML sont des aides à la décision. Les avis dont une anomalie est *confirmée par un agent* sont exclus du calcul ; les alertes non examinées rendent la recommandation « provisoire ».
* Règles des recommandations (seuils dans `apps/analytics/recommendations.py`) : échantillon minimal 30 avis ; **félicitations** = 1er, note ≥ 7 et borne basse de l'IC95 % au-dessus de la moyenne des autres ; **avertissement** = note < 5,5 (ou dernier avec < 6) ; **instruction de sanction à envisager** = note < 4 et borne haute de l'IC95 % < 5.

## Moteur ML — ce qu'il fait et ne fait pas
Dossier `ml_engine/` (doc complète : `docs/ML_ENGINE.md`). Il combine règles explicables et Isolation Forest (≥ 200 avis), valide les données, calcule des scores par dimension avec intervalles de confiance, et versionne ses modèles (`ml_engine/artifacts/`). Il est relié au backend par `ml_engine/adapter.py` (contrat 1.0).

> **Honnêteté sur le modèle.** Aucun jeu de données réel *étiqueté* (avis « fiable » / « non fiable » vérifiés par des humains) n'existe encore : le moteur est donc **non supervisé / à base de règles**. Il repère des réponses **atypiques**, il **ne prouve pas** une fraude et **n'émet aucune probabilité d'authenticité** (valeur `null`). « Aucune anomalie détectée » ne signifie pas « authentique ». Quand ARTEC aura accumulé quelques centaines d'avis étiquetés par des agents (examens humains enregistrés dans *Analyses ML*), `ml_engine.authenticity.train_supervised` permettra d'entraîner un vrai classifieur calibré, évalué par lot/période.
> Sur un jeu **synthétique** (680 avis, 80 anomalies injectées), le moteur retrouve les 80 anomalies avec 1 fausse alerte sur 600 avis normaux : cela vérifie le bon fonctionnement du code, **pas** la performance sur des données réelles.

Modèle de référence (recommandé en production, scores comparables d'un lot à l'autre) : entraîner un Isolation Forest sur un lot **validé par un humain** via `ml_engine.anomaly_detection.train_reference_model` (voir `docs/ML_ENGINE.md` §9).

## Tests
```
python manage.py test        # 184 tests (backend, frontend, intégration ML) — PostgreSQL requis, rôle avec CREATEDB
python -m pytest -q          # 19 tests du moteur ML seul (pip install -r requirements-dev.txt)
```

## Limites connues
* Les avis sont volontaires, non représentatifs, et mesurent une **perception**, pas la qualité technique du réseau.
* Pas de collecte automatique sur Facebook (API non utilisée) : les données de réseaux sociaux se chargent par **fichiers autorisés** avec provenance (*Sources*) ; la base légale (données personnelles à Madagascar) est à valider avec ARTEC.
* Les avis ne portent qu'une **date** (pas d'heure) : la détection de pics horaires est désactivée.
* Le moteur ML n'a pas de pseudonyme visiteur (vie privée) : les règles « même visiteur » sont inactives ; l'anti-spam du backend s'en charge.
* Validé sous Linux (Python 3.12, PostgreSQL 16). **Non testé sous Windows ni Python 3.11** : lancez `python manage.py test` après installation.
* Traitement ML synchrone par lot ; aucun test de charge réalisé.
* Rendu visuel non contrôlé dans un navigateur par moi : vérifiez les pages principales après installation.

## Organisation
```
config/     réglages Django, routes          apps/        comptes, feedback, datasets, complaints,
templates/  pages (public, operator, artec)               analytics (ML + recommandations), dashboard
static/     CSS, JS, Bootstrap local          ml_engine/   moteur ML + adaptateur + tests + artefacts
samples/    fichiers d'import d'exemple       docs/        contrat technique, frontend, ML, installation
scripts/    SQL de création de la base        *.bat / *.sh installation et lancement
```
