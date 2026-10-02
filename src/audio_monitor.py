"""Automatické routování zvuku pro režim 'meet'.

Řeší, aby appka mohla ZÁROVEŇ zachytávat systémový zvuk (přes BlackHole)
a ty ho přitom slyšel ve sluchátkách:

1. Přepne systémový výstup na BlackHole (zapamatuje si původní, na konci vrátí).
2. Monitor: přehrává zachycený zvuk do tvého fyzického výstupu.
   Každé ~2 s kontroluje, co je připojené, a sám se přepne
   (priorita AirPody > kabelová sluchátka > USB > repráky).

Vyžaduje `SwitchAudioSource` (brew install switchaudio-osx). Když chybí,
appka jen vypíše instrukci a poběží bez auto-routingu.
"""
import os
import shutil
import subprocess
import threading
import time
import queue

import numpy as np
import sounddevice as sd

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"

# "Upgrade" zařízení = sluchátka, na která se monitor SÁM přepne, jakmile je
# připojíš (přednost před původním výstupem). Vyšší v seznamu = preferované.
UPGRADE_KEYWORDS = [
    "airpods",
    "beats",
    "wh-",                # Sony
    "external headphones", # jack sluchátka
    "sluchátka",
    "headphone",
    "headset",
]

# Virtuální/nežádoucí zařízení, do kterých se NIKDY nemonitoruje
BLACKLIST = ["blackhole", "zoomaudiodevice", "aggregate", "multi-output"]


def _switchaudio_available() -> bool:
    return shutil.which("SwitchAudioSource") is not None


def get_system_output() -> str:
    """Vrátí název aktuálního systémového výstupu."""
    out = subprocess.run(
        ["SwitchAudioSource", "-c", "-t", "output"],
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def set_system_output(name: str) -> bool:
    """Nastaví systémový výstup podle názvu zařízení."""
    r = subprocess.run(
        ["SwitchAudioSource", "-s", name, "-t", "output"],
        capture_output=True, text=True,
    )
    return r.returncode == 0


class AudioMonitor:
    """Auto-routing systémového výstupu + adaptivní monitor do sluchátek."""

    def __init__(self, sample_rate: int = 16000, blackhole_name: str = "BlackHole",
                 monitor_device: str = None):
        self.sample_rate = sample_rate
        # Přelož podsřetězec ("BlackHole") na přesný název zařízení
        # ("BlackHole 2ch"), který SwitchAudioSource vyžaduje.
        self.blackhole_name = self._resolve_output_name(blackhole_name)
        # Ruční volba monitor výstupu (--monitor) — má přednost před vším
        self.forced_device = monitor_device

        self.available = _switchaudio_available()
        self._original_output = None      # kam vrátit výstup na konci
        self._queue: "queue.Queue" = None
        self._out_stream: sd.OutputStream = None
        self._monitor_device = None       # index aktuálního monitor výstupu
        self._running = False
        self._threads = []

    @staticmethod
    def _resolve_output_name(needle: str) -> str:
        """Najde přesný název výstupního zařízení podle podsřetězce."""
        low = needle.lower()
        for d in sd.query_devices():
            if d["max_output_channels"] > 0 and low in d["name"].lower():
                return d["name"]
        return needle  # fallback — nechá původní

    # ---- systémový výstup -------------------------------------------------

    def route_system_to_blackhole(self) -> bool:
        """Zapamatuje původní výstup a přepne systém na BlackHole."""
        if not self.available:
            print("⚠️  SwitchAudioSource není nainstalovaný — auto-routing vypnut.")
            print("    Nainstaluj: brew install switchaudio-osx")
            print(f"    Nebo ručně přepni systémový výstup na '{self.blackhole_name}'.")
            return False

        self._original_output = get_system_output()
        if self._original_output == self.blackhole_name:
            # Výstup už je BlackHole — nemáme kam vracet, radši na fyzický
            self._original_output = self._pick_physical_output_name()

        if set_system_output(self.blackhole_name):
            print(f"🔀 Systémový výstup → {self.blackhole_name} (původní: {self._original_output})")
            return True
        print(f"⚠️  Nepodařilo se přepnout výstup na {self.blackhole_name}")
        return False

    def restore_system_output(self):
        """Vrátí systémový výstup na původní zařízení."""
        if self.available and self._original_output:
            if set_system_output(self._original_output):
                print(f"🔀 Systémový výstup vrácen → {self._original_output}")

    # ---- výběr fyzického výstupu -----------------------------------------

    def _find_output_index(self, needle: str):
        """Index výstupního zařízení podle podsřetězce názvu (nebo None)."""
        if not needle:
            return None
        low = needle.lower()
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and low in d["name"].lower():
                return i
        return None

    def _pick_physical_output_name(self) -> str:
        """Název cílového výstupu (pro obnovu / logy)."""
        idx = self._pick_physical_output_index()
        return sd.query_devices(idx)["name"] if idx is not None else self.blackhole_name

    def _pick_physical_output_index(self):
        """Vybere, kam monitor přehrává. Pořadí rozhodování:

        1. Ruční volba (--monitor), pokud je připojená
        2. Připojená SLUCHÁTKA (AirPody/kabel) — kvůli tomu se přepíná za běhu
        3. Původní systémový výstup (kde uživatel poslouchal před přepnutím)
        4. Jakýkoli fyzický výstup jako fallback
        """
        # 1. ruční override
        if self.forced_device:
            idx = self._find_output_index(self.forced_device)
            if idx is not None:
                return idx

        # 2. připojená sluchátka (podle priority v UPGRADE_KEYWORDS)
        for key in UPGRADE_KEYWORDS:
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] <= 0:
                    continue
                name = d["name"].lower()
                if any(b in name for b in BLACKLIST):
                    continue
                if key in name:
                    return i

        # 3. původní výstup (kde uživatel poslouchal)
        if self._original_output and self.blackhole_name not in self._original_output:
            idx = self._find_output_index(self._original_output)
            if idx is not None:
                return idx

        # 4. fallback — první fyzický výstup mimo blacklist
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and not any(
                b in d["name"].lower() for b in BLACKLIST
            ):
                return i
        return None

    # ---- monitor ----------------------------------------------------------

    def start_monitor(self, audio_queue: "queue.Queue"):
        """Spustí přehrávání zachyceného zvuku do fyzického výstupu."""
        self._queue = audio_queue
        self._running = True
        # vlákno přehrávání + vlákno sledování změn zařízení
        t_play = threading.Thread(target=self._play_loop, daemon=True)
        t_watch = threading.Thread(target=self._watch_devices_loop, daemon=True)
        t_play.start()
        t_watch.start()
        self._threads = [t_play, t_watch]

    def _open_output(self, device_index):
        """Otevře výstupní stream na daném zařízení."""
        if self._out_stream is not None:
            try:
                self._out_stream.stop()
                self._out_stream.close()
            except Exception:
                pass
        self._out_stream = sd.OutputStream(
            device=device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
        )
        self._out_stream.start()
        self._monitor_device = device_index
        name = sd.query_devices(device_index)["name"]
        print(f"\r\033[K🎧 Monitor → {name}")

    def _play_loop(self):
        """Bere chunky z fronty a přehrává je do aktuálního výstupu."""
        # počáteční zařízení
        idx = self._pick_physical_output_index()
        if idx is not None:
            try:
                self._open_output(idx)
            except Exception as e:
                print(f"[MONITOR] Nelze otevřít výstup: {e}")

        while self._running:
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None or self._out_stream is None:
                continue
            try:
                self._out_stream.write(np.asarray(chunk, dtype=np.float32))
            except Exception as e:
                if DEBUG:
                    print(f"[MONITOR] write error: {e}")

    def _watch_devices_loop(self):
        """Každé ~2 s zkontroluje, jestli se nezměnil nejlepší výstup."""
        while self._running:
            time.sleep(2)
            if not self._running:
                break
            try:
                best = self._pick_physical_output_index()
                if best is not None and best != self._monitor_device:
                    best_name = sd.query_devices(best)["name"]
                    if DEBUG:
                        print(f"[MONITOR] změna zařízení → {best_name}")
                    self._open_output(best)
            except Exception as e:
                if DEBUG:
                    print(f"[MONITOR] watch error: {e}")

    def stop(self):
        """Zastaví monitor a vrátí systémový výstup."""
        self._running = False
        for t in self._threads:
            t.join(timeout=2)
        if self._out_stream is not None:
            try:
                self._out_stream.stop()
                self._out_stream.close()
            except Exception:
                pass
            self._out_stream = None
        self.restore_system_output()
