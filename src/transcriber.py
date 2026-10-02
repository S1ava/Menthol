"""Speech-to-text using OpenAI Whisper."""
import os
import threading
import whisper
import numpy as np
from typing import Optional

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"


class Transcriber:
    """Transcribe audio using Whisper model."""

    def __init__(self, model_size: str = "base", language: str = "cs"):
        """
        Args:
            model_size: "tiny", "base", "small", "medium", "large"
            language: Language code (e.g., "cs" for Czech, "en" for English)
        """
        self.model_size = model_size
        self.language = language
        self.model = None
        # Whisper/torch není thread-safe → serializuj přístup k modelu
        self._lock = threading.Lock()
        self._load_model()

    def _load_model(self):
        """Load Whisper model (cached after first load)."""
        print(f"Loading Whisper {self.model_size} model...")
        self.model = whisper.load_model(self.model_size)
        print("Whisper model loaded.")

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe audio to text.

        Args:
            audio_data: numpy array of audio samples
            sample_rate: sample rate (default 16000 Hz)

        Returns:
            Transcribed text
        """
        # Ochrana proti prázdnému/příliš krátkému audiu (jinak Whisper spadne
        # na reshape 0-element tensoru).
        if audio_data is None or len(audio_data) < sample_rate * 0.5:
            return ""

        try:
            if DEBUG:
                audio_min = float(audio_data.min())
                audio_max = float(audio_data.max())
                audio_mean = float(audio_data.mean())
                print(f"[WHISPER] Audio stats: min={audio_min:.4f}, max={audio_max:.4f}, mean={audio_mean:.6f}")

            # Serializuj přístup k modelu — Whisper/torch není thread-safe
            # (přepisovací smyčka i hotkey callback ho volají z různých vláken).
            with self._lock:
                result = self.model.transcribe(
                    audio_data,
                    language=self.language,
                    fp16=False,
                    initial_prompt="Toto je rozhovor v češtině.",
                )
            text = result["text"].strip()
            if DEBUG:
                print(f"[WHISPER] Full result: {result}")
            return text
        except Exception as e:
            print(f"[WHISPER] Transcription error: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def transcribe_partial(
        self, audio_data: np.ndarray, sample_rate: int = 16000
    ) -> str:
        """
        Transcribe with lower accuracy but faster (good for real-time).
        Uses smaller context window.
        """
        duration_sec = len(audio_data) / sample_rate
        if DEBUG:
            print(f"[WHISPER] transcribe_partial: {len(audio_data)} samples ({duration_sec:.2f}s)")

        min_duration = 1.0  # Minimum 1 second
        if len(audio_data) < sample_rate * min_duration:
            return ""

        # Use only last N seconds to speed up
        max_samples = sample_rate * 10  # 10 seconds
        if len(audio_data) > max_samples:
            audio_data = audio_data[-max_samples:]

        result = self.transcribe(audio_data, sample_rate)
        return result
