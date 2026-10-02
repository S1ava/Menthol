"""Zápis textového přepisu konverzace do souboru.

Ukládá do recordings/hovor_<timestamp>.txt souběžně s audio nahrávkou.
Píše průběžně (flush po každém řádku), takže i při pádu zůstane zapsané
to, co do té doby proběhlo. Zaznamenává přepis i vygenerované nápovědy.
"""
import os
import re
import threading
from datetime import datetime


def sanitize_name(name: str, max_len: int = 60) -> str:
    """Očistí název meetingu na část názvu souboru (bezpečné znaky)."""
    name = (name or "").strip()
    # Odstraň běžné Meet ozdoby v titulku tabu.
    name = re.sub(r"\s*[-–]\s*Google\s*Meet\s*$", "", name, flags=re.I)
    name = re.sub(r"^\s*Meet\s*[-–]\s*", "", name, flags=re.I)
    name = name.strip()
    # Generický titulek (nepojmenovaná schůzka) → prázdno, ať se použije kód.
    if name.lower() in ("", "meet", "google meet"):
        return ""
    # Nahraď nepovolené znaky podtržítkem, sluč mezery.
    name = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"_+", "_", name).strip("_")
    return name[:max_len]


class TranscriptLogger:
    """Průběžně zapisuje přepis hovoru a nápovědy do textového souboru."""

    def __init__(self, output_dir: str, session_stamp: str,
                 mode: str = "", role: str = ""):
        output_dir = os.path.expanduser(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        self._dir = output_dir
        self._stamp = session_stamp
        self.meeting_name = None
        self.path = os.path.join(output_dir, f"meet_{session_stamp}.txt")
        self._lock = threading.Lock()
        self._started = datetime.now()

        header = [
            "=" * 60,
            f"🌿 Menthol — přepis hovoru",
            f"{self._started.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Režim: {mode}   Role: {role}",
            "=" * 60,
            "",
        ]
        self._write_lines(header)

    def _write_lines(self, lines):
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                for ln in lines:
                    f.write(ln + "\n")
                f.flush()

    def set_meeting_name(self, name: str):
        """Zapamatuje název meetingu (z titulku Meet tabu) pro pojmenování souboru."""
        clean = sanitize_name(name)
        if clean:
            self.meeting_name = clean

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def log_transcript(self, text: str, speaker: str = None):
        """Zapíše finalizovaný úsek přepisu."""
        prefix = f"{speaker}: " if speaker else ""
        self._write_lines([f"[{self._ts()}] {prefix}{text}"])

    def log_suggestion(self, text: str):
        """Zapíše vygenerovanou nápovědu."""
        self._write_lines([f"[{self._ts()}] 💡 NÁPOVĚDA: {text}", ""])

    def close(self, usage: str = None):
        """Uzavře soubor zápatím (volitelně se souhrnem spotřeby)."""
        ended = datetime.now()
        dur = ended - self._started
        footer = [
            "",
            "=" * 60,
            f"Konec: {ended.strftime('%H:%M:%S')}   Délka session: {dur}",
        ]
        if usage:
            footer.append(usage)
        footer.append("=" * 60)
        self._write_lines(footer)

        # Přejmenuj podle názvu meetingu: meet_<stamp>_<nazev>.txt
        if self.meeting_name:
            new_path = os.path.join(
                self._dir, f"meet_{self._stamp}_{self.meeting_name}.txt"
            )
            if new_path != self.path:
                try:
                    with self._lock:
                        os.rename(self.path, new_path)
                        self.path = new_path
                except OSError as e:
                    print(f"[LOG] Přejmenování přepisu selhalo: {e}")
        print(f"📄 Přepis uložen: {self.path}")
