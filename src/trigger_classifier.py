"""Proaktivní upozornění: po každé finalizované větě rychle (Haiku) posoudí,
jestli právě teď nastalo něco, co si zaslouží okamžitou macOS notifikaci
(na rozdíl od hotkey nápovědy, kterou si uživatel vyžádá sám).

Běží asynchronně (vlastní vlákno na dotaz), ať nezdržuje zpracování přepisu.
"""
import json
import os
import subprocess
import sys
import threading
import time
import requests
from typing import Callable, List, Optional
# POZN: `anthropic` (~2,7 s import) se načítá líně v _make_anthropic_client,
# ať nezdržuje start aplikace.

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_SYSTEM_PROMPT = (
    "Sleduješ přepis hovoru v reálném čase, větu po větě. Dostaneš posledních "
    "pár vět. Posuď, jestli právě teď nastalo něco, na co si uživatel zaslouží "
    "OKAMŽITÉ upozornění — např. konkrétní námitka k ceně, zmínka konkurence, "
    "jasný signál k nákupu/rozhodnutí, nebo že hovor směřuje ke konci bez "
    "domluveného dalšího kroku. Běžné plynutí konverzace bez těchto signálů "
    "NENÍ důvod k upozornění.\n\n"
    'Odpověz VÝHRADNĚ JSON objektem: {"trigger": true/false, "note": '
    '"krátká poznámka česky, max 10 slov"}. Nic jiného nepiš. Když si '
    "nejsi jistý, trigger=false."
)


class TriggerClassifier:
    """Klasifikuje úseky přepisu na pozadí a při triggeru pošle notifikaci."""

    def __init__(
        self,
        providers: List[dict],
        system_prompt: Optional[str] = None,
        cooldown_seconds: float = 20.0,
        on_trigger: Optional[Callable[[str], None]] = None,
        sound: bool = False,
        overlay_duration: float = 3.0,
        notification_type: str = "overlay",
        overlay_func: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            providers: řetězec providerů v pořadí priority, každý
                {"provider": "gemini"|"anthropic", "model": str, "api_key": str}
        """
        self.providers = []
        for p in providers:
            provider = p["provider"]
            api_key = p.get("api_key") or (
                os.environ.get("GEMINI_API_KEY")
                if provider == "gemini"
                else os.environ.get("ANTHROPIC_API_KEY")
            )
            if not api_key:
                continue
            self.providers.append({
                "provider": provider,
                "model": p["model"],
                "api_key": api_key,
                "client": self._make_anthropic_client(api_key) if provider == "anthropic" else None,
            })

        if not self.providers:
            raise ValueError(
                "Žádný alert provider nemá nastavený API klíč (config.json nebo "
                "GEMINI_API_KEY/ANTHROPIC_API_KEY env proměnná)."
            )

        # Primární provider — pro logování/kompatibilitu s voláním zvenčí.
        self.provider = self.providers[0]["provider"]
        self.model = self.providers[0]["model"]

        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.cooldown_seconds = cooldown_seconds
        self.on_trigger = on_trigger
        self.sound = sound
        self.overlay_duration = overlay_duration
        self.notification_type = notification_type
        # In-process overlay (menubar app). Když je nastaven, použije se místo
        # spouštění overlay_notify.py jako subproces (to v py2app bundlu nejde).
        self.overlay_func = overlay_func
        self._last_fired = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _make_anthropic_client(api_key: str):
        """Líný import anthropic (~2,7 s) — až když je opravdu potřeba."""
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)

    def check_async(self, context_text: str, speaker: Optional[str] = None):
        """Spustí klasifikaci na pozadí — nikdy neblokuje volajícího."""
        if not context_text.strip():
            return
        threading.Thread(
            target=self._check, args=(context_text, speaker), daemon=True
        ).start()

    def _check(self, context_text: str, speaker: Optional[str]):
        with self._lock:
            if time.time() - self._last_fired < self.cooldown_seconds:
                return

        block = f"{speaker} říká:\n{context_text}" if speaker else context_text
        data = None
        for entry in self.providers:
            try:
                if entry["provider"] == "gemini":
                    raw = self._gemini_request(entry, block)
                else:
                    response = entry["client"].messages.create(
                        model=entry["model"],
                        max_tokens=100,
                        system=self.system_prompt,
                        messages=[{"role": "user", "content": block}],
                    )
                    raw = response.content[0].text.strip()
                data = json.loads(raw)
                break
            except Exception as e:
                if DEBUG:
                    print(f"[TRIGGER] {entry['provider']}/{entry['model']} selhal: {e}")
                continue

        if data is None:
            return

        if not data.get("trigger"):
            return

        with self._lock:
            self._last_fired = time.time()

        note = str(data.get("note", ""))[:200]
        self._notify(note)
        if self.on_trigger:
            self.on_trigger(note)

    def _gemini_request(self, entry: dict, block: str) -> str:
        """Zavolá Gemini generateContent REST endpoint, vynutí čistý JSON výstup."""
        url = f"{GEMINI_BASE_URL}/models/{entry['model']}:generateContent"
        resp = requests.post(
            url,
            params={"key": entry["api_key"]},
            json={
                "system_instruction": {"parts": [{"text": self.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": block}]}],
                "generationConfig": {
                    "maxOutputTokens": 100,
                    "responseMimeType": "application/json",
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    def _notify(self, note: str):
        safe_note = note.replace("\n", " ").strip()
        if not safe_note:
            safe_note = "Něco se děje — mrkni na hovor."

        if self.notification_type == "osascript":
            self._notify_osascript(safe_note)
        else:
            self._notify_overlay(safe_note)

    def _notify_overlay(self, safe_note: str):
        """Vlastní floating overlay uprostřed obrazovky místo systémové
        notifikace (ta je vždy vpravo nahoře, mimo pole pozornosti v hovoru)."""
        # Menubar app: in-process overlay (sdílený NSApplication). CLI: subproces.
        if self.overlay_func:
            try:
                self.overlay_func(safe_note)
            except Exception as e:
                if DEBUG:
                    print(f"[TRIGGER] in-process overlay selhal: {e}")
            return
        overlay_path = os.path.join(os.path.dirname(__file__), "overlay_notify.py")
        try:
            subprocess.Popen(
                [
                    sys.executable, overlay_path, safe_note,
                    str(self.overlay_duration), "1" if self.sound else "0",
                ],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            if DEBUG:
                print(f"[TRIGGER] Notifikace selhala: {e}")

    def _notify_osascript(self, safe_note: str):
        """Klasická systémová notifikace macOS (vpravo nahoře)."""
        # Odstraň uvozovky — brání útěku z AppleScript řetězce (transcript
        # je z hovoru, tedy fakticky externí neověřený vstup).
        escaped = safe_note.replace('"', "'")
        script = f'display notification "{escaped}" with title "🌿 Menthol upozornění"'
        if self.sound:
            script += ' sound name "Glass"'
        try:
            subprocess.run(["osascript", "-e", script], check=False)
        except Exception as e:
            if DEBUG:
                print(f"[TRIGGER] Notifikace selhala: {e}")
