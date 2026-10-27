@echo off
REM Analyse ML sur les 30 derniers jours. A planifier (Planificateur de taches Windows) toutes les heures ou chaque jour.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python manage.py run_ml_analysis --last-days 30
