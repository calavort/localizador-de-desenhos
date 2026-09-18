$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$ShortcutPath = Join-Path $Programs 'Localizador de Desenhos.lnk'
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
foreach ($Required in @($Pythonw, (Join-Path $Root 'Localizador_Desenhos.pyw'), (Join-Path $Root 'interface\localizador.ico'))) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) { throw "Arquivo ausente: $Required" }
}
[IO.Directory]::CreateDirectory($Programs) | Out-Null
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = '"' + (Join-Path $Root 'Localizador_Desenhos.pyw') + '"'
$Shortcut.WorkingDirectory = $Root
$Icon = Join-Path $Root 'interface\localizador.ico'
if (Test-Path $Icon) { $Shortcut.IconLocation = $Icon + ',0' }
$Shortcut.Description = 'Localiza e abre o PDF da ultima revisao de um desenho.'
$Shortcut.Save()
[System.Windows.Forms.MessageBox]::Show('Atalho adicionado ao Menu Iniciar.', 'Localizador de Desenhos') | Out-Null
