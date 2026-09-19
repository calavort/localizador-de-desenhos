@echo off
setlocal
title Localizador de arquivo - Menu Iniciar
set "APP_ROOT=%~dp0"
rem O codigo PowerShell que cria o atalho esta no fim deste mesmo arquivo,
rem depois da marca de secao. Manter os dois aqui evita o par .bat + .ps1
rem para uma tarefa so: o cmd sai no exit abaixo e nunca chega a ler as
rem linhas de PowerShell.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$partes = (Get-Content -LiteralPath '%~f0' -Raw) -split '(?m)^#POWERSHELL#\r?$'; Invoke-Expression $partes[1]"
set "RESULTADO=%ERRORLEVEL%"
echo.
pause
exit /b %RESULTADO%
#POWERSHELL#
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$Root = ($env:APP_ROOT).TrimEnd('\')
$Programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$ShortcutPath = Join-Path $Programs 'Localizador de arquivo.lnk'
$LegacyShortcutPath = Join-Path $Programs 'Localizador de Desenhos.lnk'

$PythonExe = $null
foreach ($Candidate in @('py.exe', 'python.exe')) {
    $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if (-not $Command) { continue }
    $Probe = @('-c', 'import sys; assert sys.version_info >= (3,11); print(sys.executable)')
    if ($Candidate -eq 'py.exe') { $Probe = @('-3') + $Probe }
    $Found = & $Command.Source @Probe 2>$null
    if ($LASTEXITCODE -eq 0 -and $Found) {
        $PythonExe = ([string]($Found | Select-Object -Last 1)).Trim()
        break
    }
}
if (-not $PythonExe) { throw 'Python 3.11 ou superior nao encontrado. Execute Instalar Bibliotecas.bat.' }

$Pythonw = Join-Path (Split-Path -Parent $PythonExe) 'pythonw.exe'
$Launcher = Join-Path $Root 'Localizador_Desenhos.pyw'
$Icone = Join-Path $Root 'interface\localizador.ico'
foreach ($Required in @($Pythonw, $Launcher, $Icone)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) { throw "Arquivo ausente: $Required" }
}

[IO.Directory]::CreateDirectory($Programs) | Out-Null
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = '"' + $Launcher + '"'
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = $Icone + ',0'
$Shortcut.Description = 'Localiza e abre arquivos PDF e DWG de um desenho.'
# Janela normal e ativada. CreateShortcut reaproveita o .lnk que ja existe,
# entao um atalho antigo gravado como minimizado continuaria abrindo o
# programa atras das outras janelas ate este campo ser gravado de novo.
$Shortcut.WindowStyle = 1
$Shortcut.Save()

if (Test-Path -LiteralPath $LegacyShortcutPath) { Remove-Item -LiteralPath $LegacyShortcutPath -Force }
[System.Windows.Forms.MessageBox]::Show('Atalho adicionado ao Menu Iniciar.', 'Localizador de arquivo') | Out-Null
