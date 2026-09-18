@echo off
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 "%~dp0Localizador_Desenhos.pyw" & exit /b)
where pythonw >nul 2>nul && (start "" pythonw "%~dp0Localizador_Desenhos.pyw" & exit /b)
echo Python nao foi encontrado. Instale o Python 3.11 ou superior.
pause
