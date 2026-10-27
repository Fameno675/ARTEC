# Moteur ML ARTEC (`ml_engine`)

Module Python **séparé** à placer dans `D:\ARTEC\ml_engine\`, appelé par Django via une fonction stable.
Il évalue la **qualité perçue** des services télécoms, repère des **observations inhabituelles** et produit
des **alertes explicables**. Il ne prononce **aucune sanction** et ne gère aucune permission.

> **État honnête du modèle.** Aucun dataset réel ni label vérifié n'a été fourni. Le moteur livré est donc
> **non supervisé / à base de règles** : il ne produit **aucune probabilité d'authenticité** et **aucune précision
> n'est revendiquée**. Les tests utilisent un jeu **FICTIF** qui vérifie le fonctionnement du code, pas sa
> performance réelle. Aucun rapport d'évaluation n'est fourni (il suppose des labels) ; l'outillage est prêt
> (`authenticity.train_supervised`).

## 1. Installation (Windows, PowerShell ou cmd)

```
cd D:\ARTEC
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r ml_engine\requirements.txt
python -m ml_engine.synthetic
python -m pytest -q
python -m ml_engine.cli ml_engine\tests\data\sample_fictif.csv --out resultat.json
```
(PowerShell : si l'activation est bloquée, `Set-ExecutionPolicy -Scope Process RemoteSigned`.)

## 2. Architecture

```
ml_engine/
  __init__.py          expose analyze_batch, EngineConfig
  schemas.py           opérateurs, critères, alias de colonnes, EngineConfig (tous seuils/poids)
  preprocessing.py     normalisation, types, pseudonymisation, journal des transformations
  validation.py        statuts accepted/review/rejected + motifs ; profil du lot
  features.py          variables comportementales (notes, horaires, volumes, répétitions)
  anomaly_detection.py règles métier -> Isolation Forest (si assez de données) -> LOF (comparaison)
  authenticity.py      classification supervisée, SEULEMENT avec labels vérifiés (outillage)
  quality_scoring.py   indicateurs descriptifs, scores par dimension, comparaison, incertitude
  prediction.py        analyze_batch(...) : orchestration + garde-fous
  model_registry.py    joblib + metadata.json + SHA-256 + retour arrière
  synthetic.py cli.py  jeu fictif ; ligne de commande
  tests/  artifacts/
```
Pas de frontend, pas de seconde application Django.

## 3. Schéma des données attendues (une ligne = un avis/une observation)

| Colonne canonique | Obligatoire | Type | Remarques / alias acceptés |
|---|---|---|---|
| `operator` | oui | texte | `Orange`, `Yas`, `Airtel` (+ « Madagascar », « MG ») ; inconnu → rejeté |
| `submitted_at` | oui | date-heure | ISO 8601 **avec décalage** (`2026-09-01T10:00:00+03:00`) ; sans décalage = UTC |
| 10 critères | ≥ 1 | nombre 0–10 | `internet_vitesse, internet_stabilite, internet_disponibilite, appels_qualite_sonore, appels_reussite, sms_fiabilite, tarification, credit_forfaits, mobile_money, service_client` ; vides autorisés (non imputés) ; virgule décimale acceptée |
| `obs_id` | non | texte | généré (`row-N`) si absent |
| `source` | non | texte | `public_review`, `operator_file`, `survey`, `external`, `complaint` ; défaut `unspecified` |
| `visitor_id` | non | texte | **jeton pseudonyme** fourni par Django (pas de donnée personnelle) ; haché salé à l'entrée |
| `batch_ref` | non | texte | lot / campagne (utile pour la validation par groupes) |
| `comment` | non | texte | non conservé : seules longueur et empreinte servent aux contrôles |
| `verified_label` | non | `fiable`/`non_fiable` ou 0/1 | uniquement si label **vérifié** par un humain |

Les noms de colonnes sont normalisés (accents, casse, espaces) : `Opérateur`, `Date de soumission`, `ID visiteur`… sont reconnus.
Les colonnes inconnues sont ignorées **et consignées** dans `preprocessing_log`.

## 4. Fonctionnement

1. **Prétraitement/validation** : lignes jamais supprimées, chacune reçoit `accepted | review | rejected` + motifs.
   Rejet : opérateur inconnu, date invalide/future/antérieure à `min_valid_date`, aucune note, note hors 0–10, doublon exact.
   À examiner : doublon probable (même visiteur+opérateur+notes à ≤10 min), valeur non numérique ignorée, `obs_id` dupliqué.
   Hook `EngineConfig.extra_rules` pour des règles de cohérence inter-champs propres à ARTEC.
2. **Scores de qualité perçue** (`quality_scoring.py`, déterministes) :
   note basse `< 4`, haute `>= 7`, moyenne entre les deux (configurables) ; score d'un critère = moyenne ;
   score d'une **dimension** (internet, appels, sms, tarification, credit_forfaits, mobile_money, service_client)
   = moyenne pondérée, par observation, des critères renseignés, puis moyenne ; **IC 95 %** (t de Student) ;
   `reliable_sample=false` si `n < min_n_reliable` (30). **Poids égaux par défaut** : tout poids est une décision
   à justifier et se règle via `criterion_weights` / `global_weights`. Le **score global** est facultatif
   (`compute_global=False` par défaut), signalé comme dépendant des poids. Une dimension n'est jamais mélangée à une autre sans ce calcul explicite.
3. **Anomalies** :
   - *Règles (référence)* : notes toutes identiques et extrêmes (≥5 critères) ; ≥5 soumissions du même pseudonyme/opérateur en 60 min ; même commentaire ≥3 fois dans le lot.
   - *Niveau groupe uniquement* : concentration horaire par opérateur (médiane + MAD, `burst_z=4`, ≥10 avis) et divergence de moyenne entre sources (≥2 points, n≥30 par source).
     **Une concentration d'avis bas n'est jamais attribuée à la fraude** : elle est décrite avec sa part de notes basses et le nombre de visiteurs distincts (panne, campagne légitime ou action concertée restent possibles).
   - *Isolation Forest* : seulement si ≥200 observations valides. Modèle enregistré s'il existe, sinon ajusté **sur le lot** (avertissement : scores relatifs au lot). Signalement statistique si score ≥ `iforest_min_score` (0,65, heuristique **à calibrer** sur données réelles) et ≥ quantile 95 % d'apprentissage.
   - *LOF* : comparaison optionnelle (`compare_detectors=True`), recouvrement entre méthodes — pas une mesure de précision.
4. **Authenticité** : statuts réellement supportés — `rejected_structural`, `needs_review`, `no_anomaly_detected`
   (**≠ authentique**), `not_assessed`, et `model_flagged_unreliable` **seulement** avec un modèle supervisé calibré et qualifié.
   `authenticity_probability` n'apparaît **que** dans ce dernier cas.
5. **Classification supervisée** (quand des labels vérifiés existeront) : `train_supervised(...)` exige ≥200 labels et ≥30 par classe,
   refuse la séparation aléatoire simple (séparation **par lot/campagne** ou **temporelle**), calibre les probabilités, et rapporte précision, rappel,
   F1, matrice de confusion, taux de faux positifs/négatifs, Brier, courbe de calibration, résultats par source/opérateur si les effectifs le permettent.
   « Qualifié » = seuil technique de la config ; la mise en service reste une décision humaine.

## 5. Garde-fous et gouvernance

- `analyze_batch` **ne lève jamais d'exception** : erreurs dans `errors`, statut `failed` (lot inanalysable) ou `partial` (ML/scoring en échec,
  validation conservée). Modèle absent → règles seules ; fichier corrompu/altéré (SHA-256) → avertissement + repli ; données insuffisantes → avertissement.
- **Enregistrez d'abord les données validées dans PostgreSQL, puis lancez l'analyse** : une erreur ML ne doit jamais bloquer l'enregistrement.
- Données personnelles minimisées : identifiant visiteur haché+salé (changer `visitor_salt` en production, le garder secret), commentaires non conservés,
  aucune tentative d'identification. Aucune collecte externe n'est faite par le moteur.
- Chaque résultat porte `model_version`, `engine_version`, `analysis_date` ; chaque alerte porte `reasons` et `evidence` consultables par l'agent.
- Aucune sanction automatique : le moteur renvoie des indicateurs, Django gère droits, décisions et traçabilité.

## 6. Limites connues

- Perception déclarée ≠ mesure technique du réseau. Avis publics sans compte : auto-sélection, non-indépendance (un visiteur, plusieurs avis), IC optimistes.
- Aucun redressement de représentativité ; comparer opérateurs/périodes/sources avec prudence (avertissements `period_mismatch`, `source_mix_mismatch`, `small_sample`).
- Un visiteur malveillant peut changer de jeton : les règles « par visiteur » sont contournables. L'absence d'anomalie ne prouve rien.
- Saisonnalité horaire non modélisée dans la détection de concentrations ; seuils (`burst_z`, `iforest_min_score`…) non calibrés sur données réelles.
- Isolation Forest sur le lot : non comparable d'un lot à l'autre ; privilégier un modèle de référence entraîné sur un historique validé (`train_reference_model`).
- Traitement **synchrone par lot**, adapté à un volume modeste. Aucun test de charge réalisé : pas de promesse « temps réel » à grande échelle.
  Pour monter en charge, appeler `analyze_batch` depuis une tâche asynchrone (Celery/RQ/Django-Q) : l'interface ne change pas.

## 7. Appel depuis Django

```python
# artec/services/ml_analysis.py
from django.db import transaction
from ml_engine import analyze_batch, EngineConfig

CFG = EngineConfig(visitor_salt=settings.ARTEC_VISITOR_SALT)   # secret, hors dépôt

def run_analysis(batch):
    qs = batch.reviews.values("id", "operator", "source", "created_at", "visitor_token",
                              "comment", "internet_vitesse", "internet_stabilite", "internet_disponibilite",
                              "appels_qualite_sonore", "appels_reussite", "sms_fiabilite", "tarification",
                              "credit_forfaits", "mobile_money", "service_client")
    result = analyze_batch(list(qs), metadata={"batch_id": str(batch.pk), "source": batch.source}, config=CFG)
    with transaction.atomic():                       # le résultat est du JSON pur
        AnalysisResult.objects.update_or_create(
            batch=batch, defaults={"payload": result, "status": result["status"],
                                   "model_version": result["model_version"]})
    return result

# à lancer APRÈS l'enregistrement des avis :
# transaction.on_commit(lambda: run_analysis(batch))
```
Colonne `payload` : `models.JSONField()` (PostgreSQL → `jsonb`). Les agents lisent `anomalies[*].reasons/evidence` ; seuls les rôles autorisés y accèdent (côté Django).

## 8. Exemple de sortie

Voir `docs/example_output.json` (extrait tronqué, **données fictives**). Clés : `batch_id, model_version, status, total_observations,
accepted/review/valid/rejected_observations, profile, preprocessing_log, validation_report, reference_period, quality_scores, trend, comparisons,
anomalies, group_anomalies, rejected, observation_results, authenticity, representativity_notes, warnings, errors`.
`status` : `ok | ok_with_warnings | partial | failed`.

## 9. Sauvegarde et versionnement des modèles

- Un modèle = un dossier `artifacts/<nom>/<AAAAMMJJThhmmss…Z>/` avec `model.joblib` + `metadata.json` (date, versions Python/sklearn/pandas, SHA-256, effectif, évaluation).
- Entraîner un modèle de référence non supervisé sur un lot **validé par un humain** :
  `train_reference_model(features, config, ModelRegistry(), note="lot sept. 2026 validé par X")`.
- Le pointeur `latest.txt` désigne la version active ; **retour arrière** : `ModelRegistry().set_latest("isolation_forest", "<ancienne_version>")`.
- Un modèle supervisé n'est activé (`latest`) que s'il est `qualified` ; le rapport d'évaluation est stocké dans ses métadonnées.
- Sauvegarder `artifacts/` (hors Git si volumineux), garder les versions sklearn identiques entre entraînement et production.
  `joblib` = pickle : ne charger que des artefacts produits par ARTEC (le SHA-256 est vérifié avant chargement).
- Re-entraîner et documenter à chaque changement important de source ou de volume ; comparer les versions sur les mêmes lots avant bascule.
