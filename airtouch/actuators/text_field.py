"""Deteccion de "estoy sobre un campo de texto".

Sirve para que el teclado virtual aparezca solo al hacer clic en algo donde se
escribe, como en el iPad. Dos estrategias, de mas a menos fiable:

  1. UI Automation: pregunta al elemento con el foco si es de tipo Edit o
     Document. Funciona en apps nativas, Chrome, Electron y UWP.
  2. Caret nativo: GetGUIThreadInfo devuelve el rectangulo del cursor de texto.
     Rapido y sin dependencias, pero solo en controles clasicos.

Si ninguna funciona no pasa nada: el teclado sigue pudiendose abrir a mano.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

UIA_EDIT = 50004
UIA_DOCUMENT = 50030
UIA_COMBOBOX = 50003
_TEXTY = {UIA_EDIT, UIA_DOCUMENT}

_EDIT_CLASSES = {
    "Edit", "RichEdit", "RichEdit20W", "RichEdit50W", "RICHEDIT60W",
    "TextBox", "Scintilla", "SysTreeView32", "ConsoleWindowClass",
}


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


class TextFieldDetector:
    def __init__(self) -> None:
        self._uia = None
        self._uia_failed = False

    # ---------------- UI Automation ----------------
    def _get_uia(self):
        if self._uia is not None or self._uia_failed:
            return self._uia
        try:
            import comtypes.client  # type: ignore

            self._uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",  # CUIAutomation8
                interface=comtypes.client.GetModule("UIAutomationCore.dll").IUIAutomation,
            )
        except Exception as exc:
            log.info("UI Automation no disponible (%s); se usara solo el caret", exc)
            self._uia_failed = True
            self._uia = None
        return self._uia

    def _focused_is_text_uia(self) -> bool | None:
        uia = self._get_uia()
        if uia is None:
            return None
        try:
            el = uia.GetFocusedElement()
            if el is None:
                return False
            ct = el.CurrentControlType
            if ct in _TEXTY:
                return True
            if ct == UIA_COMBOBOX:
                return bool(getattr(el, "CurrentIsKeyboardFocusable", False))
            return False
        except Exception:
            return None

    # ---------------- caret nativo ----------------
    @staticmethod
    def _focused_is_text_caret() -> bool:
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            return False
        if info.hwndCaret:
            r = info.rcCaret
            if (r.bottom - r.top) > 0:
                return True
        hwnd = info.hwndFocus or info.hwndActive
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value in _EDIT_CLASSES

    # ---------------- API ----------------
    def focused_is_text_field(self) -> bool:
        via_uia = self._focused_is_text_uia()
        if via_uia is not None:
            return via_uia
        return self._focused_is_text_caret()
