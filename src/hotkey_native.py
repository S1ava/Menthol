"""Globální hotkey přes Carbon RegisterEventHotKey (nativní macOS).

Proč ne pynput: pynput dělá dotaz na rozložení klávesnice (TSMGetInputSource…)
z vedlejšího vlákna, což HIToolbox v zabalené appce odmítne přes
dispatch_assert_queue → tvrdý pád (SIGTRAP). Carbon hotkey se registruje na
aplikační event target (hlavní runloop rumps), NEvyžaduje oprávnění Sledování
vstupu a stisk 'spotřebuje' (aplikace pod tím ho nedostane).

Callback se pouští ve vlákně, ať těžká práce (LLM) neblokuje UI runloop.
"""
import ctypes
import ctypes.util
import threading
from typing import Callable

_carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


kEventClassKeyboard = 0x6B657962  # 'keyb'
kEventHotKeyPressed = 6

# Carbon modifikátory
_MODS = {
    "cmd": 0x0100, "command": 0x0100,
    "shift": 0x0200,
    "alt": 0x0800, "option": 0x0800,
    "ctrl": 0x1000, "control": 0x1000,
}

# Virtuální keycody (ANSI rozložení) — písmena, číslice, F-klávesy, speciály.
_KEYS = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06,
    "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
    "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C,
    "0": 0x1D, "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23,
    "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
    "space": 0x31, "return": 0x24, "tab": 0x30, "escape": 0x35, "esc": 0x35,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}

_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

_carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
_carbon.RegisterEventHotKey.restype = ctypes.c_int
_carbon.RegisterEventHotKey.argtypes = [
    ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
    ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
]
_carbon.InstallEventHandler.restype = ctypes.c_int
_carbon.InstallEventHandler.argtypes = [
    ctypes.c_void_p, _HANDLER, ctypes.c_uint32,
    ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
]
_carbon.UnregisterEventHotKey.restype = ctypes.c_int
_carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]


def parse_combo(combo: str):
    """'cmd+shift+h' → (keycode, carbon_modifiers). Vrátí (None, 0) když nezná klávesu."""
    mods = 0
    keycode = None
    for raw in (combo or "").split("+"):
        k = raw.strip().lower()
        if not k:
            continue
        if k in _MODS:
            mods |= _MODS[k]
        elif k in _KEYS:
            keycode = _KEYS[k]
    return keycode, mods


class HotkeyListener:
    """Naslouchá globální zkratce přes Carbon a spustí callback ve vlákně."""

    def __init__(self, key_combination: str, callback: Callable):
        self.callback = callback
        self.key_combination = key_combination
        self.keycode, self.mods = parse_combo(key_combination)
        self._upp = None          # držet referenci, ať to GC nesebere
        self._hotkey_ref = None
        self._handler_ref = None
        print(f"[HOTKEY] '{key_combination}' → keycode={self.keycode} mods={self.mods}")

    def start(self):
        if self.keycode is None:
            print(f"[HOTKEY] Neznámá klávesa v '{self.key_combination}' — hotkey neaktivní")
            return
        target = _carbon.GetApplicationEventTarget()

        def _cb(next_handler, event, user_data):
            threading.Thread(target=self.callback, daemon=True).start()
            return 0

        self._upp = _HANDLER(_cb)
        spec = _EventTypeSpec(kEventClassKeyboard, kEventHotKeyPressed)
        hnd = ctypes.c_void_p()
        _carbon.InstallEventHandler(
            target, self._upp, 1, ctypes.byref(spec), None, ctypes.byref(hnd)
        )
        self._handler_ref = hnd

        hkid = _EventHotKeyID(0x4D544C31, 1)  # 'MTL1'
        ref = ctypes.c_void_p()
        res = _carbon.RegisterEventHotKey(
            self.keycode, self.mods, hkid, target, 0, ctypes.byref(ref)
        )
        self._hotkey_ref = ref
        if res != 0:
            print(f"[HOTKEY] RegisterEventHotKey selhal (kód {res})")
        else:
            print(f"[HOTKEY] Registrováno (Carbon): {self.key_combination}")

    def stop(self):
        try:
            if self._hotkey_ref:
                _carbon.UnregisterEventHotKey(self._hotkey_ref)
        except Exception:
            pass
        self._hotkey_ref = None
