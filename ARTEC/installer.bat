@echo off
REM Installation ARTEC (Windows). Double-cliquer ou lancer depuis cmd dans ce dossier.
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto nopython

if not exist .venv\Scripts\activate.bat py -3 -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 goto pipfail

if exist .env goto haveenv
copy .env.example .env >nul
python -c "import secrets,pathlib; p=pathlib.Path('.env'); p.write_text(p.read_text(encoding='utf-8').replace('remplacez-par-une-longue-valeur-aleatoire', secrets.token_urlsafe(60)), encoding='utf-8')"
echo.
echo ============================================================
echo Le fichier .env vient d'etre cree. Dans le Bloc-notes qui va s'ouvrir:
echo   1. Remplacez remplacez-moi par le mot de passe du role PostgreSQL artec.
echo   2. Verifiez la ligne DB_PORT: mettez le port de votre PostgreSQL.
echo   3. Enregistrez avec Ctrl+S puis fermez le Bloc-notes.
echo Ensuite RELANCEZ installer.bat.
echo ============================================================
notepad .env
pause
exit /b 0

:haveenv
python manage.py check
if errorlevel 1 goto fail
python manage.py migrate
if errorlevel 1 goto migfail
echo.
echo ============================================================
echo Installation terminee.
echo   - Donnees de demonstration, facultatif: demo.bat
echo   - Lancer le site: lancer.bat
echo ============================================================
pause
exit /b 0

:nopython
echo Python introuvable. Installez Python 3.12 depuis python.org en cochant Add python.exe to PATH, puis relancez.
pause
exit /b 1

:pipfail
echo Echec d'installation des dependances. Essayez ensuite: pip install -r requirements-lock.txt
pause
exit /b 1

:migfail
echo Migration impossible. Verifiez que PostgreSQL est demarre, et dans .env: DB_NAME, DB_USER, DB_PASSWORD, DB_PORT.
pause
exit /b 1

:fail
echo Une etape a echoue. Lisez le message ci-dessus.
pause
exit /b 1
