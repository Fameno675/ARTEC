@echo off
REM Cree des donnees FICTIVES (jamais en production) + comptes demo, puis lance une analyse ML.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python manage.py seed_demo_data --yes
python manage.py run_ml_analysis --last-days 365
echo.
echo Comptes demo (mot de passe : Demo-Artec-2026!) : demo.artec@example.mg, demo.orange@example.mg, demo.yas@example.mg, demo.airtel@example.mg
pause
