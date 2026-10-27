# ARTEC — Contrat technique v1.0 (backend / frontend Django / moteur ML)

Version implémentée du contrat validé. Les écarts par rapport à la proposition initiale sont listés en fin de document.

## 1. Rôles et périmètres
| Rôle (`User.role`) | Accès | Remarque |
|---|---|---|
| `operator` | `/operateur/…` | Rattaché à **un** opérateur (contrainte DB). Périmètre = `request.user.operator`, jamais d'identifiant d'opérateur dans l'URL ; un objet d'un autre opérateur renvoie **404**. |
| `artec_admin` | `/artec/…` | Seul rôle pouvant importer côté ARTEC, valider des avis, changer des statuts, prendre des décisions, examiner des anomalies. |
| `tech_admin` | `/gestion/` (admin Django) | Comptes, opérateurs, critères. **Aucun** accès à `/artec/…` : pas de décision réglementaire. |
| visiteur | pages publiques | Aucun compte requis. |
Mauvais rôle → 403 ; anonyme → redirection vers `/compte/connexion/`.

## 2. Règles métier fixes
- Notes **entières 0–10** (CHECK en base). Une note par critère est facultative ; au moins une est requise.
- Positif **7–10**, neutre **5–6**, négatif **0–4**, calculé sur les **notes**.
- `quality_score` = moyenne des notes, calculée par `apps.analytics`. `anomaly_score` ∈ [0,1], **n'est pas une probabilité**. `authenticity_probability` reste `null` tant qu'aucun modèle calibré n'existe.
- Seuil d'échantillon : 30 (`ARTEC_MIN_SAMPLE`). En dessous : signalé, non classé. Toute comparaison affiche période, n et IC 95 %.
- Les imports déclaratifs d'opérateurs (`operator_import`) sont **exclus** des comparaisons publiques et ARTEC.

## 3. Routes
| Accès | Méthode | Chemin | Nom |
|---|---|---|---|
| Public | GET | `/` | `public:home` |
| Public | GET | `/sondages/` | `public:survey_list` |
| Public | GET, POST | `/sondages/<slug>/` | `public:survey_detail` |
| Public | GET | `/sondages/<slug>/merci/` | `public:survey_thanks` |
| Public | GET | `/resultats/?operator=&start=&end=&granularity=` | `public:results` |
| Public | GET | `/methodologie/` | `public:methodology` |
| Auth | GET, POST | `/compte/connexion/` | `accounts:login` |
| Auth | POST | `/compte/deconnexion/` | `accounts:logout` |
| Auth | GET, POST | `/compte/mot-de-passe/` | `accounts:password_change` |
| Auth | GET | `/compte/redirection/` | `accounts:home_redirect` |
| Opérateur | GET | `/operateur/` | `operator:dashboard` |
| Opérateur | GET | `/operateur/imports/`, `…/<uuid>/`, `…/modele.csv`, `…/<uuid>/erreurs.csv` | `operator:import_list`, `import_detail`, `import_template`, `import_errors` |
| Opérateur | GET, POST | `/operateur/imports/nouveau/` | `operator:import_create` |
| Opérateur | GET | `/operateur/reclamations/`, `…/<reference>/` | `operator:complaint_list`, `complaint_detail` |
| Opérateur | GET, POST | `/operateur/reclamations/nouvelle/` | `operator:complaint_create` |
| Opérateur | POST | `…/<reference>/pieces/`, `…/<reference>/message/` | `operator:complaint_attach`, `complaint_reply` |
| Opérateur | GET | `…/<reference>/pieces/<id>/` | `operator:attachment_download` |
| ARTEC | GET | `/artec/`, `/artec/avis/`, `/artec/operateurs/`, `/artec/audit/` | `artec:dashboard`, `feedback_list`, `operators`, `audit` |
| ARTEC | POST | `/artec/avis/<uuid>/validation/` | `artec:feedback_validate` |
| ARTEC | GET, POST | `/artec/sondages/`, `…/nouveau/`, `…/<id>/` | `artec:survey_list`, `survey_create`, `survey_edit` |
| ARTEC | GET, POST | `/artec/imports/`, `…/nouveau/`, `…/<uuid>/` (+ `modele.csv`, `erreurs.csv`) | `artec:import_*` |
| ARTEC | GET, POST | `/artec/sources/`, `/artec/sources/nouveau/` | `artec:source_list`, `source_create` |
| ARTEC | GET | `/artec/reclamations/`, `…/<reference>/` | `artec:complaint_list`, `complaint_detail` |
| ARTEC | POST | `…/<reference>/statut/`, `…/<reference>/decision/` | `artec:complaint_status`, `complaint_decision` |
| ARTEC | GET | `…/<reference>/pieces/<id>/` | `artec:attachment_download` |
| ARTEC | GET, POST | `/artec/analyses/`, `/artec/analyses/<uuid>/` | `artec:mlbatch_list`, `mlbatch_detail` |
| ARTEC | POST | `/artec/analyses/predictions/<id>/revue/` | `artec:prediction_review` |
| Admin technique | * | `/gestion/` | — |
Listes paginées (25 par page, 50 pour l'audit), filtres en query string. POST protégés par CSRF.

## 4. Variables de contexte des templates
| Template | Variables |
|---|---|
| `public/survey_detail.html` | `survey`, `form`, `criteria_fields` (`[{criterion, field}]`), `operators`, `scale` |
| `public/results.html` | `filters`, `indicators` (liste, un par opérateur, avec `operator_name` et `series`), `min_sample`, `limitations`, `disclaimer` |
| `operator/dashboard.html` | `operator`, `period`, `indicators`, `series`, `recent_imports`, `complaints_by_status`, `import_stats` |
| `operator/import_detail.html` (aussi `artec/`) | `batch`, `summary`, `row_errors` (page), `filters` |
| `operator/complaint_detail.html` | `complaint`, `events`, `attachments`, `allegation_notice`, `attach_form`, `message_form` |
| `artec/complaint_detail.html` | idem + `decisions`, `status_form`, `decision_form` (`events` inclut les notes internes) |
| `artec/dashboard.html` | `indicators` (liste), `period`, `counts`, `import_stats`, `ml_summary`, `complaints_by_status`, `recent_reviews`, `min_sample`, `disclaimer`, `to_review_count` |
| `artec/mlbatch_detail.html` | `batch`, `predictions` (page), `reasons_legend`, `review_form` |

Format de `indicators` :
```json
{"operator":"orange","period":{"start":"2026-01-01","end":"2026-03-31","granularity":"month"},
 "n_submissions":412,"min_sample":30,"sample_sufficient":true,"quality_score":6.4,
 "sources":{"public_form":380},
 "criteria":[{"code":"mobile_data_speed","n_ratings":398,"mean":6.4,"ci95":[6.1,6.7],
   "distribution":{"0":5,"1":3,"…":0,"10":40},"positive_rate":0.52,"neutral_rate":0.21,"negative_rate":0.27,"sample_sufficient":true}],
 "limitations":["…"]}
```

## 5. Schéma d'import `feedback_import_v1`
- **CSV** UTF-8 (BOM accepté), séparateur `,` ou `;` détecté. **Excel** : `.xlsx` uniquement (feuille `feedback`, sinon la première). `.xls`, `.xlsm`, macros : refusés. Maximum 10 Mo, 50 000 lignes.
- Lecture de **valeurs** uniquement (pandas + openpyxl) : aucune formule ni macro n'est exécutée.
- En-têtes insensibles à la casse ; colonnes inconnues ignorées avec avertissement.

| Colonne | Obligatoire | Règle |
|---|---|---|
| `external_id` | non | ≤ 100 caractères |
| `operator_code` | ARTEC : oui ; opérateur : non | `orange`/`yas`/`airtel` actifs ; pour un opérateur, vide ou égal au sien |
| `collected_at` | oui | `AAAA-MM-JJ`, ni futur, ni > 5 ans |
| `score_<code critère>` ×10 | au moins une par ligne | entier 0–10 ou vide (`7.0` accepté, `7.5` refusé) |
| `comment` | non | ≤ 500 caractères |

Codes critères : `mobile_data_speed`, `mobile_data_stability`, `mobile_data_availability`, `call_audio_quality`, `call_success_stability`, `sms_reliability`, `pricing_value`, `credit_purchase_ease`, `mobile_money_reliability`, `customer_service`.

**Classement.** Rejetée : date/note/opérateur invalide, aucune note, commentaire ou identifiant trop long, doublon (fichier ou base). À examiner : notes toutes à 0 ou toutes à 10 (≥ 3 notes), date > 2 ans, URL dans le commentaire, `external_id` déjà vu avec des notes différentes. Clé de doublon : `external_id` (hash opérateur + source + id) sinon SHA-256 (opérateur, date, notes triées, source).

**Garanties.** Erreur structurelle → fichier entièrement refusé. Plus de 20 % de lignes rejetées → lot refusé, **aucun avis écrit** (le rapport de lignes est conservé). Sinon écriture en **une transaction**. Chaque import conserve : fichier (privé), SHA-256, nom, auteur, date, source, compteurs, statut (`committed`/`failed`), rapport d'erreurs CSV (cellules `= + - @` neutralisées).

## 6. Contrat ML v1.0 (`ml_engine/contract.py`)
Transport-agnostique : dataclasses Python ≡ JSON. Le backend envoie un dict :
```json
{"batch_id":"<uuid>","contract_version":"1.0","observations":[
  {"observation_id":"<uuid avis>","operator_code":"orange","collected_at":"2026-03-01","source":"public_form",
   "scores":{"mobile_data_speed":7,"customer_service":null}}]}
```
Réponse attendue :
```json
{"batch_id":"<uuid>","contract_version":"1.0","model_name":"rules_isolation_forest","model_version":"0.1.0",
 "status":"succeeded|partial|failed",
 "results":[{"observation_id":"…","is_anomaly":true,"anomaly_score":0.62,"authenticity_probability":null,
             "reasons":[{"code":"straight_lining","message":"Toutes les notes sont identiques.","feature":null}]}],
 "errors":[{"code":"…","message":"…","observation_id":null}],"processed_at":"2026-10-25T10:00:00+03:00"}
```
**Règles backend.** Seuls les avis `accepted` partent, sans `client_hash`, `device_hash` ni commentaire. Réponse validée (batch_id, version majeure, statut, identifiants connus et uniques, scores dans [0,1]) sinon lot `failed/invalid_response`. Moteur absent → `unavailable` ; exception → `failed/ml_exception` ; statut partiel → `partial`. Un `batch_id` n'est traité qu'une fois. Résultats écrits en une transaction. Aucune prédiction ne modifie une réclamation ni ne crée de décision : examen humain (`AnomalyReview`) puis, séparément, décision ARTEC avec preuves.
Choix du client : `ML_ENGINE_BACKEND=local|unavailable` dans `.env`.

## 7. Variables d'environnement (`.env`, jamais versionné)
`DJANGO_DEBUG`, `DJANGO_SECRET_KEY` (obligatoire hors debug), `DJANGO_ALLOWED_HOSTS`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `ML_ENGINE_BACKEND`, et réglages optionnels : `ARTEC_MIN_SAMPLE`, `IMPORT_MAX_FILE_BYTES`, `IMPORT_MAX_ROWS`, `IMPORT_MAX_REJECT_RATE`, `FEEDBACK_*`, `LOGIN_MAX_FAILURES`, `TRUST_X_FORWARDED_FOR`, `PRIVATE_MEDIA_ROOT`.

## 8. Écarts par rapport à la proposition validée
| Écart | Raison |
|---|---|
| `FeedbackSubmission.device_hash` et `content_hash` ajoutés | Limite « 1 avis par appareil / 24 h » sans stocker `client_hash` comme identifiant d'appareil ; distinction doublon exact / conflit d'`external_id`. |
| `Criterion.position` ajouté | Ordre d'affichage stable. |
| Route `artec:feedback_validate` ajoutée | Sans elle, les avis « à examiner » ne pourraient jamais être validés. |
| Données purgeables : `client_hash`/`device_hash` | Commande `purge_client_hashes` (30 jours) à planifier. |
