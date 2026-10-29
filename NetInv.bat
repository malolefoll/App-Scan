@echo off
rem Ouvre l'application NetInv (fenetre avec vue 3D).
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0"

rem pyw / pythonw ouvrent la fenetre sans laisser de console noire derriere
where pyw >nul 2>&1 && ( start "" pyw -3 -m netinv gui --lang fr & goto :eof )
where pythonw >nul 2>&1 && ( start "" pythonw -m netinv gui --lang fr & goto :eof )
where python >nul 2>&1 && ( python -m netinv gui --lang fr & goto :eof )

echo Python est introuvable. Installe-le depuis le Microsoft Store ou avec :
echo     winget install Python.Python.3.12
echo puis relance ce fichier.
pause
