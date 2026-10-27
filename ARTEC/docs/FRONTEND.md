# ARTEC — Frontend (Django templates, Bootstrap 5, JavaScript natif)

Compatible avec le contrat backend v1.0 : **aucune route, aucun champ ni aucune API n'a été inventé**. Chaque page utilise les URL nommées et les variables de contexte réellement fournies par les vues.

## 1. Conception et navigation

**Identité.** Marine institutionnel (`#0b1f3a`), bleu d'action (`#0f4c81`), accent sarcelle (`#0b6e78`). Les séries de graphiques (bleu, vert-sarcelle, violet, ocre) sont volontairement éloignées des couleurs commerciales des opérateurs ; un opérateur garde la même couleur partout (index fixe via `operators_map`). Typographie système (aucune police externe), cartes arrondies, ombres légères, animations limitées aux transitions courtes et désactivées par `prefers-reduced-motion`.

**Trois mises en page** (héritage `base.html`) :
- `layouts/public.html` : barre de navigation horizontale (Accueil · Opérateurs · Donner mon avis · Résultats · Méthodologie · Connexion), pied de page.
- `layouts/dashboard.html` : barre supérieure + menu latéral fixe (≥ 992 px) devenant tiroir (offcanvas) sur tablette/mobile. Le menu dépend du rôle.
- Administration technique : admin Django sur `/gestion/`, habillé (`templates/admin/base_site.html`).

**Plan de navigation**
| Espace | Entrées |
|---|---|
| Public | Accueil (mission, étapes, opérateurs couverts) → Donner mon avis (choix opérateur + sondages ouverts) → formulaire → confirmation ; Résultats ; Méthodologie ; Connexion |
| Opérateur | Tableau de bord · Imports (liste, nouveau, détail, rapport d'erreurs) · Réclamations (liste, nouvelle, détail) · Résultats publics · Mot de passe |
| ARTEC | Pilotage : Tableau de bord, Avis collectés, Analyses ML · Instruction : Réclamations · Données : Imports, Sources, Sondages · Gouvernance : Opérateurs, Journal d'audit |
| Admin technique | `/gestion/` : comptes, rôles, opérateurs, critères, journal (lecture seule) |

## 2. Arborescence
```
templates/
  base.html                      racine (CSS, modale de confirmation, barre de chargement, bannière hors-ligne)
  403.html 403_csrf.html 404.html 500.html   (500.html est autonome, sans héritage)
  admin/base_site.html
  layouts/    public.html  dashboard.html
  partials/   messages  navbar_public  account_menu  sidebar_operator  sidebar_artec  footer
              confirm_modal  pagination  field  form_fields  empty  stat  chart  chart_data
              allegation  privacy_box  indicators_card  period_filter  import_help
  accounts/   login  password_change
  public/     home  survey_list  survey_detail  survey_thanks  too_many  results  methodology
  operator/   dashboard  import_list  import_create  import_detail
              complaint_list  complaint_create  complaint_detail
  artec/      dashboard  feedback_list  operators  audit_list  survey_list  survey_form
              import_list  import_create  import_detail(*)  source_list  source_form
              complaint_list  complaint_detail  mlbatch_list  mlbatch_detail
static/
  css/  artec-base.css (jetons, typographie)  artec-components.css (composants ar-*)
        artec-public.css  artec-dashboard.css
  js/   core.js  feedback-form.js  file-upload.js  charts.js  survey-list.js
  img/  artec-mark.svg  favicon.svg
  vendor/ bootstrap 5.3.3 (css+js)  bootstrap-icons 1.11.3 (css+polices)   — MIT, licences incluses
tests_js/  frontend.test.js  dump_pages.py
```
(*) `artec/import_detail.html` étend `operator/import_detail.html` : un seul gabarit, URL résolues d'après l'espace de noms courant (`operator` ou `artec`).

## 3. Routes, variables et échanges
Toutes les routes ci-dessous sont **confirmées** (contrat backend v1.0). Les formulaires POST portent `{% csrf_token %}` ; les retours utilisent les messages Django (`partials/messages.html`).

| Page (template) | Route nommée · méthodes | Variables utilisées |
|---|---|---|
| `public/home` | `public:home` GET | `operators` |
| `public/survey_list` | `public:survey_list` GET | `surveys` (+ `operators_map` du frontend) |
| `public/survey_detail` | `public:survey_detail` GET, POST | `survey`, `form`, `criteria_fields`, `scale` ; champs POST : `operator`, `score_<code>` ×10, `comment`, `form_ts`, `website` (piège) |
| `public/survey_thanks` | `public:survey_thanks` GET | `survey` |
| `public/too_many` | réponse 429 de `survey_detail` | — |
| `public/results` | `public:results` GET `?operator&start&end&granularity` | `filters`, `indicators` (liste, avec `operator_name`, `series`), `operators`, `min_sample`, `limitations`, `disclaimer` |
| `public/methodology` | `public:methodology` GET | `min_sample`, `limitations` |
| `accounts/login`, `password_change` | `accounts:login` GET/POST · `accounts:password_change` · `accounts:logout` **POST** | formulaire Django |
| `operator/dashboard` | `operator:dashboard` GET | `operator`, `period`, `indicators`, `series`, `recent_imports`, `complaints_by_status`, `import_stats` |
| `operator/import_*` | `import_list`, `import_create` GET/POST (multipart : `file`), `import_detail`, `import_errors`, `import_template` | `batches`, `form`, `batch`, `summary`, `row_errors`, `filters` |
| `operator/complaint_*` | `complaint_list`, `complaint_create` POST, `complaint_detail`, `complaint_attach` POST, `complaint_reply` POST, `attachment_download` | `complaints`, `filters`, `statuses`, `form`, `allegation_notice`, `complaint`, `events`, `attachments`, `attach_form`, `message_form` |
| `artec/dashboard` | `artec:dashboard` GET `?start&end&granularity` | `indicators` (avec `series`), `period`, `counts`, `import_stats`, `ml_summary`, `complaints_by_status`, `recent_reviews`, `min_sample`, `disclaimer`, `to_review_count` |
| `artec/feedback_list` | `artec:feedback_list` GET `?operator&status&source` ; `artec:feedback_validate` POST `decision=accept|reject` | `submissions`, `filters`, `operators`, `statuses`, `sources` |
| `artec/operators`, `audit_list` | `artec:operators`, `artec:audit` GET `?action=` | `operators` (annotés), `entries`, `filters` |
| `artec/survey_*` | `survey_list`, `survey_create`/`survey_edit` GET/POST | `surveys`, `form` (`title, slug, description, starts_at, ends_at, is_active, criteria_selection`), `survey` |
| `artec/import_*`, `source_*` | `import_list/create/detail/errors/template`, `source_list`, `source_create` | idem opérateur + `form.data_source` ; `sources`, `form` |
| `artec/complaint_*` | `complaint_list` GET `?status&complainant&target` ; `complaint_detail` ; `complaint_status` POST (`status`, `note`, `visible_to_complainant`) ; `complaint_decision` POST (`decision_type`, `evidence_summary`) | `complaints`, `complaint`, `events`, `attachments`, `decisions`, `status_form`, `decision_form` |
| `artec/mlbatch_*` | `mlbatch_list` GET/POST (`operator`, `start`, `end`) ; `mlbatch_detail` GET `?anomalies=1` ; `prediction_review` POST (`outcome`, `notes`) | `batches`, `form`, `batch`, `predictions`, `reasons_legend`, `review_form` |

**Graphiques.** Aucune API JSON : les données des vues sont sérialisées dans la page par `json_script` (`indicators-data`, `series-data`, `sources-data`, `import-data`, `complaints-data`, `batch-data`, plus `criteria-map` et `operators-map`). `charts.js` les lit et dessine du SVG. Chaque graphique est doublé d'un tableau HTML équivalent. Aucune statistique fictive n'est présente dans les templates.

**Paramètre côté client uniquement.** `?operator=<code>` sur `survey_list`/`survey_detail` présélectionne l'opérateur ; le serveur l'ignore, l'opérateur reste choisi et validé dans le formulaire.

## 4. Ajouts côté Django (petits, à confirmer par le backend)
| Fichier | Changement | Pourquoi |
|---|---|---|
| `apps/dashboard/templatetags/artec_ui.py` (nouveau) | balises `criteria_map`, `operators_map`, `import_columns`, `active_nav`, `status_badge` ; filtres `bs`, `get_item`, `pct`, `reason_label`, `initials`, `sum_by`, `merge_sources`, `open_complaints` | libellés français des critères (le contrat ne fournit que les codes), badges de statut, rendu accessible des champs. Lecture seule, aucune écriture en base. |
| `apps/dashboard/views.py` (1 ligne) | `i["series"] = ind.time_series(...)` dans `artec_dashboard` | le tableau de bord ARTEC doit afficher l'évolution temporelle par opérateur ; la fonction existait déjà. |
| `apps/analytics/views.py` (1 ligne) | `prefetch_related("submission__ratings__criterion")` dans `mlbatch_detail` | afficher les « observations justificatives » d'une alerte sans requêtes N+1 (testé : < 30 requêtes). |
| `apps/dashboard/management/commands/seed_demo_data.py` (nouveau) | données fictives étiquetées « DÉMO » ; refuse hors `DEBUG` sans `--force` ; `--purge` | vérifier l'interface avec des données non réelles. |
| `apps/dashboard/tests_frontend.py`, `tests.py`, `analytics/tests.py` | nouveaux tests ; deux assertions de textes assouplies | couvrir le rendu. |

Aucune modification de `settings.py`, `urls.py`, des modèles ni des migrations.

## 5. Décisions et manques à valider avec le backend
1. **Sondages propres à un opérateur** : non prévus par le contrat v1.0 → **non implémentés** (aucune route).
2. **Profil** : le backend n'a que le changement de mot de passe ; le menu du compte affiche nom, e-mail, rôle, opérateur et ce lien.
3. **Administration technique** : écrans fournis par l'admin Django (`/gestion/`), simplement habillés.
4. **Limite de 10 Mo / 50 000 lignes** : le backend lit `IMPORT_MAX_FILE_BYTES`/`IMPORT_MAX_ROWS` mais ne les passe pas aux templates ; la valeur par défaut (10 Mo) est écrite dans `data-max-bytes`. Proposition : exposer ces réglages dans le contexte des vues d'import.
5. **Texte de confidentialité** (`partials/privacy_box.html`, `public/methodology.html`) : rédigé d'après le comportement réel du backend (pseudonymes supprimés après 30 jours, pas de compte). **À faire valider par ARTEC** (obligations légales malgaches).
6. **Aperçu avant import** : CSV seulement (en-têtes, séparateur, premières lignes). Excel : nom, taille, format ; la vérification complète reste serveur.
7. **Nombre d'avis à examiner** dans le menu : non affiché (il faudrait un processeur de contexte) ; il l'est sur le tableau de bord et dans la liste des avis.
8. **Indicateurs opérateur** : `compute_indicators` ne renvoie pas `operator_name` ; le gabarit passe le nom via `card_title`.

## 6. Intégration dans D:\ARTEC (sans rien écraser)
```powershell
cd D:\ARTEC
Copy-Item -Recurse D:\ARTEC D:\ARTEC_backup_avant_frontend        # sauvegarde
Expand-Archive ARTEC_frontend.zip -DestinationPath D:\ARTEC_frontend_tmp
# Comparer avant de copier : les templates/ et static/css/artec.css du backend sont des maquettes minimales remplacées par ce frontend.
robocopy D:\ARTEC_frontend_tmp D:\ARTEC /E /XC /XN /XO        # /XC /XN /XO : ne remplace AUCUN fichier existant, ajoute seulement les nouveaux ; fusionnez ensuite à la main les fichiers déjà présents
.\.venv\Scripts\Activate.ps1
python manage.py check
python manage.py test                                           # backend + frontend
python manage.py seed_demo_data --yes                           # données FICTIVES (DEBUG=True requis)
python manage.py runserver
```
Comptes de démonstration (mot de passe `Demo-Artec-2026!`) : `demo.artec@example.mg`, `demo.orange@example.mg`, `demo.yas@example.mg`, `demo.airtel@example.mg`. Suppression : `python manage.py seed_demo_data --purge`.
Les fichiers de `static/` sont trouvés par `STATICFILES_DIRS` existant. En production : `python manage.py collectstatic`.
**Fichiers obsolètes** (non référencés, supprimables après vérification) : `templates/partials/form.html`, `indicators.html`, `series.html`, `static/css/artec.css`.
**Dépendances** : Bootstrap 5.3.3 et Bootstrap Icons 1.11.3 **embarqués** dans `static/vendor/` (aucun CDN : la plateforme reste utilisable avec une connexion limitée). Aucun Node, aucun build. `jsdom` n'est requis que pour `tests_js/` (outil de test, facultatif).

## 7. Tests
**Automatiques (exécutés ici)**
- `python manage.py test apps.dashboard` : rendu de 30 pages (tous rôles), un seul `h1`, lien d'évitement, `lang="fr"`, aucune variable non rendue, aucun CDN, CSRF sur tous les POST, existence de tous les fichiers statiques référencés, 403/302 selon le rôle, données JSON des graphiques, attributs `data-*` bien formés, messages Django, pages 404/403/CSRF/500/429, écran d'alerte ML, bornage du nombre de requêtes.
- `node tests_js/frontend.test.js` (après `npm install jsdom` et `python tests_js/dump_pages.py`) : 89 vérifications sur les vraies pages (formulaire 0–10, clavier, progression, graphiques, aperçu d'import, confirmation, filtre, hors-ligne, injection de HTML).
- Contrastes WCAG calculés (texte ≥ 4,5:1 ; composants graphiques ≥ 3:1) : toutes les paires utilisées passent.

**Scénarios manuels** (à jouer dans un navigateur)
1. *Visiteur* : accueil → « Donner mon avis » → choisir Yas → noter 3 critères → laisser les autres vides → envoyer → page de confirmation. Revenir, évaluer Orange : accepté. Réévaluer Yas aussitôt : message « déjà évalué ».
2. *Erreurs* : envoyer sans opérateur, puis sans note : messages clairs, focus sur le premier problème. Désactiver JavaScript : le formulaire reste utilisable (select + champs numériques).
3. *Opérateur* : se connecter → tableau de bord → importer `samples/exemple_import_operateur.csv` (aperçu avant envoi, confirmation, résumé) → importer un fichier cassé (rapport d'erreurs téléchargeable) → déposer une réclamation avec pièce.
4. *Isolation* : connecté en Orange, ouvrir manuellement l'URL d'un import ou d'une réclamation de Yas : 404.
5. *ARTEC* : tableau de bord (filtre de période, graphiques, alertes) → Analyses ML → ouvrir un lot → déplier « Observations justificatives » → enregistrer un examen avec confirmation → Réclamations : passer « en examen », enregistrer une décision motivée.
6. *Panne ML* : `ML_ENGINE_BACKEND=unavailable`, relancer un lot : bandeau « en attente ou en échec », données intactes.

**Vérification ordinateur / mobile** (outils de développement du navigateur, F12 → mode appareil)
- Largeurs 360, 768, 1280 px : menu latéral → tiroir sous 992 px ; tableaux défilants horizontalement dans leur conteneur, pas de défilement de la page ; boutons de notes sur 2 lignes (6 par ligne) sous 576 px.
- Zoom 200 % et texte agrandi : aucune coupure du contenu.
- Clavier seul : lien d'évitement, ordre de tabulation, anneau de focus visible, flèches/Début/Fin sur les notes, modale de confirmation (Échap).
- Lecteur d'écran : groupes de notes annoncés « n sur 10, libellé », messages en `role="status"/"alert"`, graphiques avec `aria-label` et tableau équivalent.
- `prefers-reduced-motion` : activer « réduire les animations » dans le système.
- Hors-ligne : couper le réseau dans l'onglet Réseau : bannière rouge.
- Lighthouse (Accessibilité, Bonnes pratiques) sur `/`, `/sondages/satisfaction-generale/`, `/artec/`.

## 8. Bilan
**Terminé et vérifié automatiquement** : 33 pages + 5 pages d'erreur, tous les rôles, formulaire dynamique 0–10, aperçu d'import, graphiques SVG sur données réelles, interface d'examen d'alerte ML (anomalie détectée → vérification en cours → décision humaine), confirmations, états vides, messages.
**Non vérifié** : le rendu visuel dans un navigateur réel (aucun navigateur disponible ici : mise en page, alignements, comportement du tiroir Bootstrap, lisibilité des graphiques sur mobile non vus à l'écran) ; Lighthouse ; lecteur d'écran. jsdom n'effectue aucun calcul de mise en page.
**Non fourni** : sondages propres à un opérateur, écran de profil, écrans d'administration technique sur mesure (admin Django à la place), aperçu des fichiers Excel.
