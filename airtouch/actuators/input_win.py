"""Inyeccion de entrada real en Windows via SendInput.

Se usa SendInput y no pyautogui porque es la API nativa: soporta arrastre
fiable, rueda horizontal, coordenadas absolutas sobre el escritorio virtual y
DPI mixto.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from ..core.screen import virtual_screen

user32 = ctypes.WinDLL("user32", use_last_error=True)

# --- constantes ---
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

WHEEL_DELTA = 120

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
VK_DELETE = 0x2E
VK_HOME, VK_END = 0x24, 0x23


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


# marca propia para reconocer nuestros eventos y no confundirlos con el raton real
AIRTOUCH_SIGNATURE = 0xA17A17


def _send(*inputs: INPUT) -> int:
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def _mouse(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(
        dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0,
        ctypes.cast(ctypes.c_void_p(AIRTOUCH_SIGNATURE), ctypes.POINTER(wintypes.ULONG)),
    ))


def _key(vk: int, flags: int = 0, scan: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
        vk, scan, flags, 0,
        ctypes.cast(ctypes.c_void_p(AIRTOUCH_SIGNATURE), ctypes.POINTER(wintypes.ULONG)),
    ))


# ---------------- raton ----------------
def move_to(x: float, y: float) -> None:
    vs = virtual_screen()
    nx = int(round((x - vs.x) * 65535 / max(vs.w - 1, 1)))
    ny = int(round((y - vs.y) * 65535 / max(vs.h - 1, 1)))
    nx = max(0, min(65535, nx))
    ny = max(0, min(65535, ny))
    _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))


def left_down() -> None:
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))


def left_up() -> None:
    _send(_mouse(MOUSEEVENTF_LEFTUP))


def left_click() -> None:
    _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))


def double_click() -> None:
    left_click()
    left_click()


def right_click() -> None:
    _send(_mouse(MOUSEEVENTF_RIGHTDOWN), _mouse(MOUSEEVENTF_RIGHTUP))


def middle_click() -> None:
    _send(_mouse(MOUSEEVENTF_MIDDLEDOWN), _mouse(MOUSEEVENTF_MIDDLEUP))


def scroll(delta_notches: float) -> None:
    amount = int(round(delta_notches * WHEEL_DELTA))
    if amount:
        _send(_mouse(MOUSEEVENTF_WHEEL, data=amount))


def hscroll(delta_notches: float) -> None:
    amount = int(round(delta_notches * WHEEL_DELTA))
    if amount:
        _send(_mouse(MOUSEEVENTF_HWHEEL, data=amount))


# ---------------- teclado ----------------
def key_down(vk: int) -> None:
    _send(_key(vk))


def key_up(vk: int) -> None:
    _send(_key(vk, KEYEVENTF_KEYUP))


def tap(vk: int) -> None:
    _send(_key(vk), _key(vk, KEYEVENTF_KEYUP))


def chord(mods: list[int], vk: int) -> None:
    seq = [_key(m) for m in mods]
    seq += [_key(vk), _key(vk, KEYEVENTF_KEYUP)]
    seq += [_key(m, KEYEVENTF_KEYUP) for m in reversed(mods)]
    _send(*seq)


def type_unicode(text: str) -> None:
    """Escribe texto arbitrario sin depender de la distribucion del teclado."""
    seq: list[INPUT] = []
    for ch in text:
        for code in _utf16_units(ch):
            seq.append(_key(0, KEYEVENTF_UNICODE, code))
            seq.append(_key(0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, code))
    if seq:
        # SendInput acepta lotes, pero troceamos para no pasarnos de tamano
        for i in range(0, len(seq), 32):
            _send(*seq[i:i + 32])


def _utf16_units(ch: str) -> list[int]:
    encoded = ch.encode("utf-16-le")
    return [int.from_bytes(encoded[i:i + 2], "little") for i in range(0, len(encoded), 2)]


def zoom(delta_notches: float) -> None:
    """Ctrl + rueda: el zoom estandar en navegadores, Office, exploradores..."""
    amount = int(round(delta_notches * WHEEL_DELTA))
    if not amount:
        return
    _send(_key(VK_CONTROL))
    _send(_mouse(MOUSEEVENTF_WHEEL, data=amount))
    _send(_key(VK_CONTROL, KEYEVENTF_KEYUP))
