"""Realtime přepis přes Google Cloud Speech-to-Text streaming API.

Na rozdíl od batch varianty (transcriber_google.py) neposílá izolované úseky,
ale souvislý audio proud. Hranice vět/slov určuje Google server-side
(endpointing + VAD), takže se slova neřežou uprostřed.

Stream má u Googlu limit ~5 minut, proto se automaticky restartuje.
"""
import os
import queue
import threading
import time
import numpy as np
from typing import Callable, Optional

try:
    from google.cloud import speech_v1
    from google.oauth2 import service_account
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"

# Google zavírá stream po ~5 min (290 s). Restartujeme s rezervou.
STREAM_RESTART_SECONDS = 240


class GoogleStreamingTranscriber:
    """Přepisuje živý audio proud přes Google streaming API."""

    def __init__(
        self,
        language: str = "cs-CZ",
        sample_rate: int = 16000,
        credentials_path: Optional[str] = None,
        on_final: Optional[Callable[[str], None]] = None,
        on_interim: Optional[Callable[[str], None]] = None,
    ):
        """
        Args:
            language: kód jazyka (cs-CZ)
            sample_rate: vzorkovací frekvence vstupu
            credentials_path: cesta k service-account JSON (None → ADC)
            on_final: callback pro hotový úsek (is_final=True)
            on_interim: callback pro průběžný text (is_final=False)
        """
        if not GOOGLE_AVAILABLE:
            raise ImportError(
                "Google Cloud Speech není nainstalované. Spusť: pip install google-cloud-speech"
            )

        self.language_code = language
        self.sample_rate = sample_rate
        self.on_final = on_final
        self.on_interim = on_interim

        if credentials_path and os.path.exists(credentials_path):
            creds = service_account.Credentials.from_service_account_file(credentials_path)
            self.client = speech_v1.SpeechClient(credentials=creds)
        else:
            # ADC (gcloud auth application-default login)
            self.client = speech_v1.SpeechClient()

        self._streaming_config = speech_v1.StreamingRecognitionConfig(
            config=speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                language_code=language,
                enable_automatic_punctuation=True,
            ),
            interim_results=True,
        )

        self._audio_queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._restart_at = 0.0
        self.restart_count = 0  # kolikrát se stream obnovil (limit 5 min)
        self.audio_seconds_sent = 0.0  # kolik audia reálně odešlo na Google
        self._pending_interim = ""  # nezfinalizovaný text aktuálního segmentu

    def start(self, audio_queue: queue.Queue):
        """Spustí přepis nad danou frontou audio chunků (numpy float32)."""
        if self._running:
            return
        self._audio_queue = audio_queue
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("[GOOGLE-STREAM] Streaming přepis spuštěn")

    def stop(self):
        """Zastaví přepis."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        print("[GOOGLE-STREAM] Streaming přepis zastaven")

    def _audio_generator(self):
        """Yielduje audio requesty; skončí při restartu streamu nebo zastavení."""
        while self._running and time.time() < self._restart_at:
            try:
                chunk = self._audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if chunk is None or len(chunk) == 0:
                continue
            # float32 (-1..1) → int16 PCM, jak Google očekává u LINEAR16
            pcm = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            # Google účtuje odeslaný audio čas (i ticho) — počítej sekundy
            self.audio_seconds_sent += len(chunk) / self.sample_rate
            yield speech_v1.StreamingRecognizeRequest(audio_content=pcm)

    def _run(self):
        """Hlavní smyčka: drží stream otevřený a před limitem ho obnoví."""
        while self._running:
            self._restart_at = time.time() + STREAM_RESTART_SECONDS
            self._pending_interim = ""  # nezfinalizovaný text v tomto segmentu
            try:
                responses = self.client.streaming_recognize(
                    config=self._streaming_config,
                    requests=self._audio_generator(),
                )
                self._handle_responses(responses)
            except Exception as e:
                if self._running:
                    print(f"[GOOGLE-STREAM] Chyba streamu: {e}")
                    time.sleep(1)  # krátká pauza před obnovením
            else:
                if self._running:
                    self.restart_count += 1
                    mins = STREAM_RESTART_SECONDS // 60
                    # Šedě a decentně — nastane jen ~1× za 4 min
                    print(
                        f"\r\033[K\033[90m↻ stream obnoven (#{self.restart_count}, "
                        f"po {mins} min — limit Googlu je 5)\033[0m"
                    )
            # Konec segmentu: pokud Google nestihl finalizovat, „zapíšeme"
            # rozpracovaný text jako finální, ať se u restartu neztratí
            if self._pending_interim and self.on_final:
                self.on_final(self._pending_interim)
                self._pending_interim = ""

    def _handle_responses(self, responses):
        """Zpracuje odpovědi: průběžné vs. finální výsledky."""
        for response in responses:
            if not self._running:
                return
            for result in response.results:
                if not result.alternatives:
                    continue
                text = result.alternatives[0].transcript.strip()
                if not text:
                    continue
                if result.is_final:
                    self._pending_interim = ""  # finalizováno Googlem
                    if self.on_final:
                        self.on_final(text)
                else:
                    self._pending_interim = text  # zapamatuj pro případ restartu
                    if self.on_interim:
                        self.on_interim(text)
