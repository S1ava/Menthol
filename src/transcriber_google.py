"""Speech-to-text using Google Cloud Speech-to-Text API."""
import os
import numpy as np
from typing import Optional

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"

try:
    from google.cloud import speech_v1
    from google.oauth2 import service_account
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


class GoogleTranscriber:
    """Transcribe audio using Google Cloud Speech-to-Text API."""

    def __init__(self, language: str = "cs-CZ", credentials_path: Optional[str] = None):
        """
        Args:
            language: Language code (e.g., "cs-CZ" for Czech)
            credentials_path: Path to Google service account JSON
        """
        if not GOOGLE_AVAILABLE:
            raise ImportError(
                "Google Cloud Speech not installed. Run: pip install google-cloud-speech"
            )

        self.language_code = language
        self.credentials_path = credentials_path

        # Load credentials
        if credentials_path and os.path.exists(credentials_path):
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path
            )
            self.client = speech_v1.SpeechClient(credentials=credentials)
        else:
            # Use default credentials (GOOGLE_APPLICATION_CREDENTIALS env var)
            self.client = speech_v1.SpeechClient()

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribe audio to text.

        Args:
            audio_data: numpy array of audio samples (float32, -1.0 to 1.0)
            sample_rate: sample rate (default 16000 Hz)

        Returns:
            Transcribed text
        """
        if len(audio_data) == 0:
            return ""

        try:
            # Convert float32 to int16 (Google API requirement)
            audio_int16 = (audio_data * 32767).astype(np.int16)

            # Create audio content
            audio = speech_v1.RecognitionAudio(content=audio_int16.tobytes())

            # Configure recognition
            config = speech_v1.RecognitionConfig(
                encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                language_code=self.language_code,
                enable_automatic_punctuation=True,
            )

            # Perform recognition
            if DEBUG:
                print("[GOOGLE-STT] Sending request...")
            response = self.client.recognize(config=config, audio=audio)

            # Extract transcript
            transcript = ""
            for result in response.results:
                if result.alternatives:
                    transcript += result.alternatives[0].transcript + " "

            return transcript.strip()

        except Exception as e:
            print(f"[GOOGLE-STT] Error: {e}")
            return ""

    def transcribe_partial(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """Rychlý přepis pro průběžnou smyčku (stejné rozhraní jako Whisper)."""
        # Přeskoč příliš krátké audio (min 0.5 s)
        if audio_data is None or len(audio_data) < sample_rate * 0.5:
            return ""
        return self.transcribe(audio_data, sample_rate)
