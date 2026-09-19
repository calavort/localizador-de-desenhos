"""Uma janela por vez.

A pasta de dados do WebView2 so aceita um processo por vez. Abrir o programa
duas vezes - pela pasta e pelo Menu Iniciar, por exemplo - faz a segunda
inicializacao falhar com "Recurso solicitado em uso" (0x800700AA), e o
pywebview mostra a janela assim mesmo: vazia e travada, sem dizer o motivo.
O mutex resolve isso na origem, trazendo para a frente a janela que ja existe.
"""

from __future__ import annotations

import ctypes
import os
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
