@echo off
rem Scan en ligne de commande puis ouverture d'un rapport HTML (dossier "rapports").
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title NetInv - rapport rapide

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo Python est introuvable. Installe-le depuis le Microsoft Store ou avec :
  echo     winget install Python.Python.3.12
  echo puis relance ce fichier.
  goto :fin
)

echo ============================================
echo   NetInv - inventaire du reseau local
echo ============================================
echo.
echo Reseau a scanner (ex : 192.168.1.0/24).
set "CIBLE="
set /p "CIBLE=Laisse vide et appuie sur Entree pour ton reseau actuel : "
echo.

set "PYTHONPATH=%~dp0"
if not exist "%~dp0rapports" mkdir "%~dp0rapports"
set "RAPPORT=%~dp0rapports\inventaire-reseau.html"

if defined CIBLE (
  %PY% -m netinv scan %CIBLE% --lang fr -o "%RAPPORT%"
) else (
  %PY% -m netinv scan --lang fr -o "%RAPPORT%"
)
if errorlevel 1 goto :fin

echo.
echo Ouverture du rapport dans ton navigateur...
start "" "%RAPPORT%"

:fin
echo.
pause
