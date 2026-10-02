"""Nahrávání audio proudu do souboru (OGG/MP3/FLAC/WAV).

Zapisuje průběžně po chuncích, takže i při pádu aplikace zůstane
nahrané to, co do té doby proběhlo.
"""
import os
import queue
import threading
from datetime import datetime
from typing import Optional

import numpy as np
import soundfile as sf

# formát → (přípona, subtype pro libsndfile)
FORMATS = {
    "OGG": ("ogg", "VORBIS"),
    "MP3": ("mp3", "MPEG_LAYER_III"),
    "FLAC": ("flac", "PCM_16"),
    "WAV": ("wav", "PCM_16"),
}


class AudioRecorder:
    """Ukládá živý audio proud do zvukového souboru."""

    def __init__(
        self,
        output_dir: str = "recordings",
        sample_rate: int = 16000,
        fmt: str = "OGG",
        session_stamp: str = None,
        label: str = "",
    ):
        self.sample_rate = sample_rate
        self.fmt = fmt.upper()
        if self.fmt not in FORMATS:
            raise ValueError(
                f"Nepodporovaný formát '{fmt}'. Použij: {', '.join(FORMATS)}"
            )

        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        ext, self.subtype = FORMATS[self.fmt]
        # Sdílený timestamp → audio a přepis mají stejný název souboru.
        # label (např. "ja") přidá příponu: hovor_<stamp>_ja.ogg
        stamp = session_stamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        suffix = f"_{label}" if label else ""
        self.path = os.path.join(output_dir, f"hovor_{stamp}{suffix}.{ext}")

        self._queue: Optional[queue.Queue] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self, audio_queue: queue.Queue):
        """Spustí zápis z dané fronty audio chunků."""
        if self._running:
            return
        self._queue = audio_queue
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"⏺️  Nahrávám do: {self.path}")

    def _run(self):
        try:
            with sf.SoundFile(
                self.path,
                mode="w",
                samplerate=self.sample_rate,
                channels=1,
                format=self.fmt,
                subtype=self.subtype,
            ) as f:
                while self._running:
                    try:
                        chunk = self._queue.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if chunk is None or len(chunk) == 0:
                        continue
                    f.write(np.asarray(chunk, dtype=np.float32))
        except Exception as e:
            print(f"[REC] Chyba nahrávání: {e}")

    def stop(self):
        """Ukončí nahrávání a dopíše soubor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if os.path.exists(self.path):
            size_mb = os.path.getsize(self.path) / (1024 * 1024)
            print(f"⏹️  Nahrávka uložena: {self.path} ({size_mb:.1f} MB)")
