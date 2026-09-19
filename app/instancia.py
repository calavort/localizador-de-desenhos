"""Uma janela por vez, e saida limpa quando o WebView2 nao sobe.

A pasta de dados do WebView2 so aceita um processo por vez. Abrir o programa
duas vezes - ou reabrir logo depois de fechar, enquanto os
``msedgewebview2.exe`` filhos ainda estao morrendo - faz a inicializacao
falhar com "Recurso solicitado em uso" (0x800700AA). O pywebview registra o
erro mas mostra a janela assim mesmo: ela aparece vazia e travada, sem dizer
o motivo. O mutex evita o caso comum; a varredura, que custa caro, so roda
quando a pagina realmente nao carregou.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

MUTEX_NOME = "Local\\Calavort.LocalizadorDesenhos.Instancia"
JANELA_TITULO = "Localizador de arquivo"
ERROR_ALREADY_EXISTS = 183

_reserva = None  # o handle precisa viver enquanto o processo viver


def reservar_instancia() -> bool:
    """True quando esta e a unica janela; False quando ja existe outra."""
    global _reserva
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, MUTEX_NOME)
        if not handle:
            return True  # sem reserva possivel nao e motivo para nao abrir
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _reserva = handle
        return True
    except Exception:
        return True


def focar_janela_existente() -> bool:
    """Traz para a frente a janela que ja esta aberta."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        for nome in ("SetForegroundWindow", "IsIconic", "BringWindowToTop"):
            getattr(user32, nome).argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

        hwnd = user32.FindWindowW(None, JANELA_TITULO)
        if not hwnd:
            return False
        SW_RESTORE, SW_SHOW = 9, 5
        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def encerrar_webview_preso(storage_path: str) -> int:
    """Encerra o WebView2 que ficou segurando a pasta de dados.

    So chame com a reserva de instancia na mao: sem outra janela viva, todo
    processo apontando para essa pasta e sobra de uma execucao anterior.
    """
    if os.name != "nt" or not storage_path:
        return 0
    script = (
        "$alvo = $env:LOCALIZADOR_STORAGE;"
        "$presos = Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" |"
        " Where-Object { $_.CommandLine -and $_.CommandLine.Contains($alvo) };"
        "$presos | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };"
        "($presos | Measure-Object).Count"
    )
    try:
        ambiente = os.environ.copy()
        ambiente["LOCALIZADOR_STORAGE"] = os.path.abspath(storage_path)
        concluido = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            env=ambiente,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
            check=False,
        )
        return int((concluido.stdout or "0").strip() or 0)
    except Exception:
        return 0


def aviso(texto: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, texto, JANELA_TITULO, 0x40)
    except Exception:
        pass
