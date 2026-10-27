#!/usr/bin/env bash
# Installation ARTEC (Linux / macOS). PostgreSQL doit deja tourner (voir scripts/creer_base.sql).
set -e
cd "$(dirname "$0")"
python3 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  key=$(python -c "import secrets; print(secrets.token_urlsafe(60))")
  sed -i.bak "s/remplacez-par-une-longue-valeur-aleatoire/$key/" .env && rm -f .env.bak
  echo ">>> .env cree : renseignez DB_PASSWORD, creez la base (scripts/creer_base.sql), puis relancez ce script."; exit 0
fi
python manage.py check && python manage.py migrate
echo "OK. Demo : python manage.py seed_demo_data --yes ; Lancer : python manage.py runserver"
