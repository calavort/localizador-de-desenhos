@echo off
setlocal
title Localizador de Desenhos - Menu Iniciar
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Adicionar ao Menu Iniciar.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %INSTALL_RESULT%
