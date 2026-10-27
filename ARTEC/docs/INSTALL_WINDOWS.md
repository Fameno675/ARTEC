# Installation et lancement (Windows / PowerShell)

> Le code a été développé et testé sous Linux (Python 3.12, PostgreSQL 16). Le projet vise Python 3.11/3.12 sous Windows : relancez la suite de tests chez vous (étape 7).

## 0. Raccourci
Les scripts `installer.bat`, `demo.bat`, `lancer.bat` et `analyser.bat` automatisent les étapes 1 à 7 ci-dessous. Ce document sert de référence et de dépannage.

## 1. Environnement Python 3.11
```powershell
cd D:\ARTEC
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
# (le moteur ML est inclus dans requirements.txt)
```

## 2. PostgreSQL (sans toucher à une installation existante)
Ouvrez `psql` avec un compte administrateur existant. Le rôle et la base sont créés **seulement s'ils n'existent pas** :
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost
```
```sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'artec') THEN
    CREATE ROLE artec LOGIN PASSWORD 'CHANGEZ-MOI' CREATEDB;
  END IF;
END $$;
SELECT 'CREATE DATABASE artec OWNER artec' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='artec') \gexec
\q
```
(`CREATEDB` est nécessaire pour que `manage.py test` crée sa base temporaire.)

## 3. Fichier `.env`
```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(60))"   # collez le résultat dans DJANGO_SECRET_KEY
notepad .env                                                   # renseignez DB_PASSWORD, etc.
```

## 4. Vérifications avant migration
```powershell
python manage.py check
python manage.py showmigrations
python manage.py makemigrations --check --dry-run
```
**Modèle utilisateur personnalisé** : `AUTH_USER_MODEL` doit être en place avant la première migration de `auth`/`admin`. Si `showmigrations` montre `admin` ou `auth` déjà appliqués sur votre base de développement, créez une **nouvelle** base (ex. `artec_v2`) plutôt que de modifier l'ancienne.

## 5. Migrations et premier compte
```powershell
python manage.py migrate
python manage.py createsuperuser        # crée un administrateur technique (role=tech_admin)
```
Les migrations chargent les 3 opérateurs, les 10 critères et un sondage par défaut (ré-exécutables sans doublon). Ensuite, sur `http://127.0.0.1:8000/gestion/` créez : un compte **Administrateur ARTEC** (`role = artec_admin`) et un compte **opérateur** par opérateur (`role = operator` + opérateur obligatoire).

## 6. Lancer le serveur
```powershell
python manage.py runserver
```
Pages : `/` (public), `/compte/connexion/`, `/operateur/`, `/artec/`, `/gestion/`.

## 7. Tests
```powershell
python manage.py test                    # 140 tests (exécutés ici sous Linux)
python manage.py test apps.datasets -v 2 # un seul module
```

## 8. Tâches utiles
```powershell
python manage.py run_ml_analysis --start 2026-01-01 --end 2026-03-31 --operator orange
python manage.py purge_client_hashes     # à planifier chaque jour (Planificateur de tâches Windows)
```
Exemples de fichiers conformes : `samples\exemple_import_artec.csv`, `.xlsx`, `exemple_import_operateur.csv`.

## 9. Avant une mise en production
`DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` réel, HTTPS, `python manage.py check --deploy`, sauvegardes de la base et de `private_media\`, cache partagé (Redis/base) pour la limitation de connexion si plusieurs processus.
