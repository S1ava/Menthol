"""Globální hotkey přes pynput (macOS/Linux/Windows).

Používá keyboard.GlobalHotKeys, který robustně řeší kombinace s modifikátory.
Vyžaduje na macOS oprávnění "Sledování vstupu" (Input Monitoring).
"""
import threading
from typing import Callable
from pynput import keyboard


class HotkeyListener:
    """Naslouchá globální klávesové zkratce a spustí callback."""

    def __init__(self, key_combination: str, callback: Callable):
        """
        Args:
            key_combination: např. "cmd+shift+h", "ctrl+alt+h", nebo "h"
            callback: funkce zavolaná při stisku zkratky
        """
        self.callback = callback
        self.key_combination = key_combination
        self.hotkey_str = self._to_pynput_format(key_combination)
        self.listener = None
        print(f"[HOTKEY] Zkratka '{key_combination}' → pynput formát '{self.hotkey_str}'")

    def _to_pynput_format(self, combo: str) -> str:
        """Převede 'cmd+shift+h' na pynput formát '<cmd>+<shift>+h'."""
        modifiers = {
            "cmd": "<cmd>",
            "command": "<cmd>",
            "ctrl": "<ctrl>",
            "control": "<ctrl>",
            "shift": "<shift>",
            "alt": "<alt>",
            "option": "<alt>",
        }
        parts = []
        for raw in combo.split("+"):
            key = raw.strip().lower()
            if not key:
                continue
            parts.append(modifiers.get(key, key))
        return "+".join(parts)

    def _on_activate(self):
        """Zavoláno při stisku zkratky. Callback běží ve vlastním vlákně,
        aby těžká práce (přepis + LLM) neblokovala event tap."""
        print("[HOTKEY] ✅ Zkratka stisknuta")
        threading.Thread(target=self.callback, daemon=True).start()

    def start(self):
        """Spustí naslouchání."""
        if self.listener:
            print("[HOTKEY] Listener už běží")
            return
        self.listener = keyboard.GlobalHotKeys({self.hotkey_str: self._on_activate})
        self.listener.start()
        print(f"[HOTKEY] Listener spuštěn (zkratka: {self.key_combination})")

    def stop(self):
        """Zastaví naslouchání."""
        if self.listener:
            self.listener.stop()
            self.listener = None
            print("[HOTKEY] Listener zastaven")
