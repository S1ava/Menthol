"""Zdroj přepisu z Google Meet titulků (přes browser extension), ne z audia.

Tváří se navenek stejně jako ostatní transcribery (start/stop + on_final/
on_interim callbacky), takže main.py ho může použít beze změny orchestrace.
Extension (browser-extension/) škrábe DOM titulků a posílá věty sem přes
lokální WebSocket.
"""
import asyncio
import json
import threading
import time
from typing import Callable, Optional

import websockets

DEBUG = False


class MeetCaptionsTranscriber:
    """WS server naslouchající browser extension místo přepisu audia."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        on_final: Optional[Callable[[str, Optional[str]], None]] = None,
        on_interim: Optional[Callable[[str, Optional[str]], None]] = None,
        on_meta: Optional[Callable[[str], None]] = None,
    ):
        self.host = host
        self.port = port
        self.on_final = on_final
        self.on_interim = on_interim
        self.on_meta = on_meta
        # Čas posledního heartbeatu (meta) z extension — pro auto-stop hlídač.
        self.last_meta_ts = None
        # Kompatibilita s main.py souhrnem spotřeby — titulky nic nestojí.
        self.audio_seconds_sent = 0.0

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._running = False

    def start(self, *_args, **_kwargs):
        """Spustí WS server na pozadí. Argumenty se ignorují — main.py volá
        start(audio_queue) i pro ostatní transcribery, tady zdroj není audio."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        self._running = False
        # Vzbudit _serve() přes Event (ne loop.stop()) — jinak se websockets.serve
        # nestihne čistě zavřít uvnitř "async with" a při GC to hodí
        # "RuntimeError: Event loop is closed".
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread:
            self._thread.join(timeout=3)
        print("[MEET-CAP] WS server zastaven")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _serve(self):
        async with websockets.serve(self._handle_client, self.host, self.port):
            print(f"[MEET-CAP] Čekám na extension na ws://{self.host}:{self.port}")
            await self._stop_event.wait()

    async def _handle_client(self, websocket):
        print("[MEET-CAP] Extension připojena")
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type")
                if mtype == "meta":
                    self.last_meta_ts = time.time()
                    title = (msg.get("title") or "").strip()
                    code = (msg.get("code") or "").strip()
                    if self.on_meta:
                        self.on_meta(title, code)
                    continue
                speaker = msg.get("speaker")
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                if DEBUG:
                    print(f"[MEET-CAP] {mtype} {speaker}: {text}")
                if mtype == "final" and self.on_final:
                    self.on_final(text, speaker)
                elif mtype == "interim" and self.on_interim:
                    self.on_interim(text, speaker)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            print("[MEET-CAP] Extension odpojena")
