"""LLM handler for Claude API a Gemini s automatickým fallbackem mezi providery."""
import os
import re
import requests
from typing import List, Optional
# POZN: `anthropic` (~2,7 s import) se načítá líně v _make_anthropic_client,
# ať nezdržuje start, když se používá jen Gemini nebo žádná nápověda ještě nebyla.

DEBUG = os.environ.get("ASSISTANT_DEBUG", "0") == "1"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def last_sentences(text: str, n: int = 5) -> str:
    """Vrátí posledních n vět z textu."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    parts = [p.strip() for p in parts if p.strip()]
    return " ".join(parts[-n:])


class LLMHandler:
    """Handle requests to Claude/Gemini API. Providery zkouší v pořadí priority a
    při chybě (rate limit, timeout, ...) automaticky přeskočí na dalšího v řetězci."""

    # Výchozí prompt (fallback, když role nedodá vlastní)
    DEFAULT_SYSTEM_PROMPT = (
        "Jsi zkušený seniorní obchodník a v reálném čase mě koučuješ během "
        "obchodního hovoru. Na základě přepisu mi poraď, na co se teď zeptat "
        "nebo co říct.\n\nPravidla:\n"
        "- Odpovídej POUZE konkrétní radou nebo otázkou, žádný úvod.\n"
        "- Krátce: maximálně 1–2 věty.\n- Odpovídej česky."
    )

    def __init__(
        self,
        providers: List[dict],
        timeout_seconds: int = 3,
        system_prompt: Optional[str] = None,
    ):
        """
        Args:
            providers: řetězec providerů v pořadí priority, každý
                {"provider": "gemini"|"anthropic", "model": str, "api_key": str}
        """
        self.timeout_seconds = timeout_seconds
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

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
            entry = {
                "provider": provider,
                "model": p["model"],
                "api_key": api_key,
                "client": self._make_anthropic_client(api_key) if provider == "anthropic" else None,
            }
            self.providers.append(entry)

        if not self.providers:
            raise ValueError(
                "Žádný LLM provider nemá nastavený API klíč (config.json nebo "
                "GEMINI_API_KEY/ANTHROPIC_API_KEY env proměnná)."
            )

        # Primární provider — pro logování/kompatibilitu s voláním zvenčí.
        self.provider = self.providers[0]["provider"]
        self.model = self.providers[0]["model"]

        self.conversation_history = []

    @staticmethod
    def _make_anthropic_client(api_key: str):
        """Líný import anthropic (~2,7 s) — až když je opravdu potřeba."""
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)

    def get_suggestion(
        self, transcript: str, context: str = "", speaker: Optional[str] = None,
        n_sentences: int = 5,
    ) -> str:
        """
        Get AI suggestion for what to say next.

        Args:
            transcript: Recent conversation transcript
            context: Additional context about the meeting/call
            speaker: kdo v přepisu mluví (např. "Klient"), nebo None
            n_sentences: kolik posledních vět poslat jako kontext

        Returns:
            AI suggestion as text
        """
        if not transcript.strip():
            return ""

        # Ponech jen posledních N vět jako kontext
        recent = last_sentences(transcript, n=n_sentences)

        # Označ mluvčího, pokud ho známe (režim meet → "Klient")
        if speaker:
            transcript_block = f"{speaker} říká:\n{recent}"
        else:
            transcript_block = f"Přepis hovoru:\n{recent}"

        # Build user message with context
        user_message = f"""{transcript_block}

{f'Kontext: {context}' if context else ''}

Na co se mám teď zeptat nebo co říct?"""

        last_error = None
        for entry in self.providers:
            try:
                if DEBUG:
                    print(f"[LLM] Sending request to {entry['model']} ({entry['provider']})...")
                if entry["provider"] == "gemini":
                    result = self._gemini_request(entry, user_message)
                else:
                    response = entry["client"].messages.create(
                        model=entry["model"],
                        max_tokens=150,
                        system=self.system_prompt,
                        messages=[
                            {"role": "user", "content": user_message}
                        ],
                    )
                    result = response.content[0].text.strip()
                if DEBUG:
                    print(f"[LLM] Got response: {result}")
                return result
            except Exception as e:
                print(f"[LLM] {entry['provider']}/{entry['model']} selhal: {e}")
                if DEBUG:
                    import traceback
                    traceback.print_exc()
                last_error = e
                continue

        return f"(Chyba LLM: {self._extract_error_message(last_error)[:150]})"

    def complete(self, system_prompt: str, user_message: str, max_tokens: int = 800) -> str:
        """Jednorázové volání s vlastním system promptem (pro brief/shrnutí)."""
        last_error = None
        for entry in self.providers:
            try:
                if entry["provider"] == "gemini":
                    url = f"{GEMINI_BASE_URL}/models/{entry['model']}:generateContent"
                    resp = requests.post(
                        url, params={"key": entry["api_key"]},
                        json={
                            "system_instruction": {"parts": [{"text": system_prompt}]},
                            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                            "generationConfig": {"maxOutputTokens": max_tokens},
                        },
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    response = entry["client"].messages.create(
                        model=entry["model"],
                        max_tokens=max_tokens,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_message}],
                    )
                    return response.content[0].text.strip()
            except Exception as e:
                print(f"[LLM] complete {entry['provider']} selhal: {e}")
                last_error = e
                continue
        return f"(Chyba LLM: {self._extract_error_message(last_error)[:150]})"

    def _gemini_request(self, entry: dict, user_message: str) -> str:
        """Zavolá Gemini generateContent REST endpoint (žádný SDK, jen requests)."""
        url = f"{GEMINI_BASE_URL}/models/{entry['model']}:generateContent"
        resp = requests.post(
            url,
            params={"key": entry["api_key"]},
            json={
                "system_instruction": {"parts": [{"text": self.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": {"maxOutputTokens": 150},
            },
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    @staticmethod
    def _extract_error_message(e: Optional[Exception]) -> str:
        """Vytáhne čitelnou chybovou hlášku z Anthropic i Gemini/requests výjimky."""
        if e is None:
            return "neznámá chyba"
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            return body.get("error", {}).get("message", str(e))
        response = getattr(e, "response", None)
        if response is not None:
            try:
                err_json = response.json()
                if isinstance(err_json, dict):
                    return err_json.get("error", {}).get("message", str(e))
            except Exception:
                pass
        return str(e)

    def add_to_history(self, role: str, content: str):
        """Add message to conversation history."""
        self.conversation_history.append(
            {"role": role, "content": content}
        )
        # Keep only last 20 messages to save tokens
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
