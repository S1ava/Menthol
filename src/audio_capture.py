"""Audio capture from microphone using sounddevice."""
import os
import queue
import sounddevice as sd
import numpy as np
from collections import deque
from threading import Thread, Event
from typing import Optional

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"


def resolve_input_device(device):
    """Najde vstupní zařízení podle názvu nebo indexu.

    Indexy zařízení se mění podle toho, co je zrovna připojené, proto se
    v configu zadává název (např. "BlackHole") a hledá se podsřetězcem.

    Args:
        device: None (výchozí mikrofon), int (index), nebo str (část názvu)

    Returns:
        index zařízení, nebo None pro systémový výchozí vstup
    """
    if device is None or isinstance(device, int):
        return device

    needle = str(device).lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
            return idx

    available = [
        d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0
    ]
    raise ValueError(
        f"Vstupní zařízení '{device}' nenalezeno.\n"
        f"Dostupná: {', '.join(available)}"
    )


class AudioCapture:
    """Capture audio from microphone in real-time."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 100,
        input_device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)
        self.input_device = input_device

        self.stream = None
        self.is_recording = False
        self.audio_buffer = deque(maxlen=sample_rate * 60)  # 60 seconds buffer
        self._recording_thread = None
        self._stop_event = Event()
        # Odběratelé živého proudu (streaming STT, nahrávání do souboru…)
        self._subscribers = []

    def subscribe(self) -> "queue.Queue":
        """Zaregistruje odběratele živého audio proudu.

        Vrací frontu, do které padá každý příchozí chunk (numpy float32).
        Umožňuje více nezávislých konzumentů nad jedním mikrofonem.
        """
        q = queue.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue"):
        """Odhlásí odběratele."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback function for audio stream."""
        if status:
            print(f"[AUDIO] Status: {status}")
        # Add incoming audio to buffer
        audio_data = indata[:, 0].astype(np.float32)  # Convert to float32
        self.audio_buffer.extend(audio_data)

        # Rozešli chunk odběratelům (musí být rychlé — jsme v realtime callbacku)
        for q in self._subscribers:
            q.put(audio_data.copy())

        # Debug every 100 frames
        if DEBUG and len(self.audio_buffer) % 1600 == 0:  # ~100ms at 16kHz
            print(f"[AUDIO] Buffer size: {len(self.audio_buffer)} samples ({len(self.audio_buffer)/self.sample_rate:.1f}s)")

    def start(self):
        """Start capturing audio."""
        if self.is_recording:
            return

        self.is_recording = True
        self._stop_event.clear()

        try:
            self.stream = sd.InputStream(
                device=self.input_device,
                samplerate=self.sample_rate,
                channels=1,
                callback=self._audio_callback,
                blocksize=self.chunk_size,
            )
            self.stream.start()
        except Exception as e:
            print(f"Error starting audio stream: {e}")
            self.is_recording = False
            raise

    def get_audio_buffer(self, duration_seconds: int) -> np.ndarray:
        """Get last N seconds of audio as numpy array."""
        num_samples = min(duration_seconds * self.sample_rate, len(self.audio_buffer))
        audio_data = np.array(list(self.audio_buffer)[-num_samples:])
        return audio_data

    def stop(self):
        """Stop capturing audio."""
        self.is_recording = False
        self._stop_event.set()
        if self.stream:
            self.stream.stop()
            self.stream.close()

    def cleanup(self):
        """Clean up resources."""
        self.stop()
