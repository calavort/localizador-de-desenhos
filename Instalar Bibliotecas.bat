@echo off
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt
if errorlevel 1 python -m pip install -r requirements.txt
echo.
echo Instalacao concluida. Pressione qualquer tecla para fechar.
pause >nul
