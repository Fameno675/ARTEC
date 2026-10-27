# Bilan (état au 27/10/2026) — projet fusionné backend + frontend + moteur ML

## Vérifié (Linux, Python 3.12, PostgreSQL 16, Django 5.2), sur une copie propre installée depuis zéro
- Installation : venv neuf, `pip install -r requirements.txt`, base créée par `scripts/creer_base.sql`, `migrate`, `seed_demo_data`, `run_ml_analysis`.
- **184 tests Django** (backend, frontend, intégration ML, recommandations), **19 tests du moteur ML** (pytest), **89 vérifications JavaScript** (jsdom, sur pages réelles).
- Lot ML de démonstration : 258 avis analysés, 6 anomalies fictives injectées, toutes signalées ; page Recommandations affichée pour chaque rôle autorisé.
- Évaluation **synthétique** du moteur (680 avis, 80 anomalies injectées) : 80/80 retrouvées, 1 fausse alerte sur 600. Vérifie le code, pas la performance réelle.

## Ajouts de la fusion
- `ml_engine/adapter.py` : contrat backend 1.0 ↔ moteur complet (`analyze_batch`). `ML_ENGINE_BACKEND=local` (défaut), `local_basic` (ancien moteur v0.1, repli), `unavailable`.
- Règle ML `extreme_only_ratings` (notes uniquement extrêmes mais non identiques).
- Page **Recommandations** ARTEC (félicitations / avertissement / instruction de sanction), fenêtre glissante 7/30/90 jours, exclusion des anomalies confirmées, résultat « provisoire » si le ML n'a pas couvert la fenêtre ou si trop d'alertes ne sont pas examinées.
- `run_ml_analysis --last-days N` (à planifier), scripts d'installation Windows/Linux, `requirements.txt` fusionné (+ `requirements-lock.txt`).

## Non vérifié / limites
- **Jamais exécuté sous Windows ni Python 3.11.** Les scripts `.bat` n'ont pas été lancés sur Windows.
- Rendu visuel **non contrôlé dans un navigateur** (tests de structure et de JavaScript uniquement).
- **Aucun modèle supervisé** : pas de données étiquetées. Le moteur est non supervisé / à base de règles ; il ne fournit aucune probabilité d'authenticité. Performance sur données réelles inconnue ; seuils (`iforest_min_score`, recommandations) à calibrer avec ARTEC.
- Avis datés au jour (pas d'heure) : détection de pics horaires désactivée ; pas d'identifiant visiteur côté ML (vie privée).
- Pas de collecte automatique Facebook : import de fichiers autorisés avec provenance. Conformité légale (données personnelles à Madagascar) à valider.
- Anti-spam basé sur le cache de processus (LocMem) et sur un cookie : insuffisant avec plusieurs processus ; ML synchrone ; pas de test de charge.
- Avis `to_review` exclus des indicateurs et du ML tant qu'un agent ne les a pas validés.
