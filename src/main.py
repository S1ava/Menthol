"""Main orchestrator for real-time meeting assistant (Menthol)."""
# Okamžitá zpětná vazba PŘED těžkými importy (anthropic/google/sounddevice ~5 s),
# jinak start "vypadá zaseknutě" a uživatel ho Ctrl+C přeruší.
print("🌿 Menthol se spouští…", flush=True)

import os

# Ztlum ukecané gRPC INFO logy (fork_posix / ev_poll_posix hlášky).
# MUSÍ být nastaveno dřív, než se naimportuje google.cloud / grpc.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")
os.environ.setdefault("GLOG_minloglevel", "2")

import sys
import time
import atexit
import signal
import shutil
import argparse
import subprocess
import textwrap
from pathlib import Path
from threading import Thread, Event, Lock
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# numpy/sounddevice/audio_capture jsou potřeba jen pro audio režimy (meet/mobil).
# Captions režim (výchozí a jediný podporovaný build) je nepotřebuje, proto se
# importují líně a jejich absence nebrání spuštění celé appky.
try:
    import numpy as np
except Exception:
    np = None

try:
    import sounddevice as sd
    from src.audio_capture import AudioCapture, resolve_input_device
    AUDIO_AVAILABLE = True
except Exception:
    sd = None
    AUDIO_AVAILABLE = False
# POZN: src.transcriber (Whisper→torch) se importuje líně až ve větvi
# provideru "whisper" — jinak by torch zdržoval start i při Google STT.
from src.llm_handler import LLMHandler
from src.ui import TerminalUI
# POZN: src.hotkey (pynput→Quartz/pyobjc, ~5 s) se importuje líně v __init__,
# aby šlo hned vypsat úvodní hlášku a start "nevypadal zaseknutě".
from src.config import load_config, get_default_config

# Try to import Google transcribers (optional)
try:
    from src.transcriber_google import GoogleTranscriber
    from src.transcriber_google_streaming import GoogleStreamingTranscriber
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

# Nahrávání hovoru do souboru (volitelné)
try:
    from src.recorder import AudioRecorder
    RECORDER_AVAILABLE = True
except ImportError:
    RECORDER_AVAILABLE = False

# Auto-routing + monitor pro režim 'meet' (volitelné)
try:
    from src.audio_monitor import AudioMonitor
    MONITOR_AVAILABLE = True
except ImportError:
    MONITOR_AVAILABLE = False

# Titulky z Google Meet přes browser extension (volitelné, potřebuje websockets)
try:
    from src.caption_server import MeetCaptionsTranscriber
    CAPTIONS_AVAILABLE = True
except ImportError:
    CAPTIONS_AVAILABLE = False

from src.trigger_classifier import TriggerClassifier

from datetime import datetime
from src.transcript_logger import TranscriptLogger


def format_usage(seconds: float, pricing: dict) -> str:
    """Sestaví řádek se spotřebou: čas + odhadovaná cena v USD."""
    minutes = seconds / 60.0
    per_min = pricing.get("google_stt_usd_per_minute", 0.016)
    cost = minutes * per_min
    m, s = divmod(int(seconds), 60)
    return (
        f"Využitý čas: {m}m {s}s ({minutes:.2f} min)   "
        f"Odhadovaná cena: ${cost:.4f} USD"
    )


class RealtimeAssistant:
    """Main application orchestrator."""

    def __init__(self, config_path: str = "config.json", mode: str = None,
                 monitor_device: str = None, role: str = None,
                 internal_speakers: list = None, on_suggestion=None,
                 overlay_func=None):
        self.config = load_config(config_path) if os.path.exists(config_path) else get_default_config()
        self._monitor_device = monitor_device
        # Volitelný callback pro zobrazení nápovědy (menubar app → overlay).
        # Když je None, nápověda se vytiskne do terminálu (CLI běh).
        self.on_suggestion = on_suggestion
        # In-process overlay pro proaktivní upozornění (menubar app). CLI: None.
        self.overlay_func = overlay_func
        # Jména mluvčích, kteří NEJSOU klient (kolegové/obchodní partneři) —
        # z config.json + dočasné doplnění přes --internal-speaker. Funguje
        # jen v captions módu, kde přicházejí reálná jména z Meet titulků.
        self.internal_speakers = {
            s.strip() for s in
            (self.config.get("internal_speakers", []) or []) + (internal_speakers or [])
            if s.strip()
        }
        # Jeden timestamp pro celou session (audio + přepis mají stejný název)
        self._session_stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.ui = TerminalUI(width=self.config["ui"]["width"])
        # Zobrazovat průběžný (interim) text během mluvení?
        self.show_interim = self.config["ui"].get("show_interim", True)

        # Režim určuje, odkud bereme zvuk (mikrofon vs. systémový přes BlackHole)
        audio_cfg = self.config["audio"]
        modes = audio_cfg.get("modes", {})
        self.mode = mode or audio_cfg.get("default_mode", "mobil")

        if self.mode not in modes:
            raise ValueError(
                f"Neznámý režim '{self.mode}'. Dostupné: {', '.join(modes)}"
            )

        mode_cfg = modes[self.mode]
        # V režimu meet je zachycená řeč vždy klient; v mobil je to mix (None)
        self.speaker = mode_cfg.get("speaker")
        # captions: zdroj je text z browser extension, žádné audio se nezachytává
        self.use_captions = (self.mode == "captions")

        print(f"🎧 Režim '{self.mode}' — {mode_cfg.get('popis', '')}")

        self.meet_app_path = None
        self.meet_url = None
        if self.use_captions:
            self.audio = None
            self.meet_app_path = mode_cfg.get("meet_app")
            self.meet_url = mode_cfg.get("meet_url")
        else:
            if not AUDIO_AVAILABLE:
                print("❌ Audio režimy (meet/mobil) vyžadují sounddevice + numpy,")
                print("   které tenhle build nemá. Použij --mode captions.")
                sys.exit(1)
            device = resolve_input_device(mode_cfg.get("device"))
            dev_name = (
                sd.query_devices(device)["name"] if device is not None
                else sd.query_devices(kind="input")["name"]
            )
            print(f"   Vstup: {dev_name}")
            self.audio = AudioCapture(
                sample_rate=audio_cfg["sample_rate"],
                chunk_duration_ms=audio_cfg["chunk_duration_ms"],
                input_device=device,
            )

        # Initialize transcriber based on config
        self.streaming = False  # True → výsledky chodí callbackem, ne pollingem

        if self.use_captions:
            if not CAPTIONS_AVAILABLE:
                print("❌ websockets není nainstalované! Instaluj: pip install websockets")
                sys.exit(1)
            self.provider = "meet_captions"
            self.transcriber = MeetCaptionsTranscriber(
                port=self.config["transcription"].get("captions_port", 8765),
                on_final=self._on_final_transcript,
                on_interim=self._on_interim_transcript,
                on_meta=self._on_meta,
            )
            self.streaming = True
            print("✓ Zdroj: titulky Google Meet (browser extension)")
        else:
            provider = self.config["transcription"].get("provider", "whisper")
            self.provider = provider

            if provider == "google_streaming":
                if not GOOGLE_AVAILABLE:
                    print("❌ Google Cloud Speech není nainstalované!")
                    print("   Instaluj: pip install google-cloud-speech")
                    print("   Přepínám na Whisper...")
                    provider = "whisper"
                else:
                    try:
                        self.transcriber = GoogleStreamingTranscriber(
                            language="cs-CZ",
                            sample_rate=self.config["audio"]["sample_rate"],
                            credentials_path=self.config["transcription"].get("google_credentials"),
                            on_final=self._on_final_transcript,
                            on_interim=self._on_interim_transcript,
                        )
                        self.streaming = True
                        print("✓ Google Speech-to-Text (streaming)")
                    except Exception as e:
                        print(f"⚠️ Streaming transcriber error: {e}")
                        print("   Přepínám na Whisper...")
                        provider = "whisper"

            if provider == "google":
                if not GOOGLE_AVAILABLE:
                    print("❌ Google Cloud Speech not installed!")
                    print("   Install with: pip install google-cloud-speech")
                    print("   Falling back to Whisper...")
                    provider = "whisper"
                else:
                    try:
                        creds_path = self.config["transcription"].get("google_credentials")
                        self.transcriber = GoogleTranscriber(
                            language="cs-CZ",
                            credentials_path=creds_path,
                        )
                        print(f"✓ Using Google Speech-to-Text")
                    except Exception as e:
                        print(f"⚠️ Google transcriber error: {e}")
                        print("   Falling back to Whisper...")
                        provider = "whisper"

            if provider == "whisper":
                # Líný import — natáhne torch až tady, ne při startu s Google STT
                from src.transcriber import Transcriber
                self.transcriber = Transcriber(
                    model_size=self.config["transcription"]["model"],
                    language=self.config["transcription"]["language"],
                )
                print(f"✓ Using Whisper ({self.config['transcription']['model']})")

        # Nahrávání hovoru do souboru (volitelné) — captions mode nemá audio
        self.recorder = None
        rec_cfg = self.config.get("recording", {})
        if not self.use_captions and rec_cfg.get("enabled") and RECORDER_AVAILABLE:
            try:
                self.recorder = AudioRecorder(
                    output_dir=rec_cfg.get("output_dir", "recordings"),
                    sample_rate=self.config["audio"]["sample_rate"],
                    fmt=rec_cfg.get("format", "OGG"),
                    session_stamp=self._session_stamp,
                )
            except Exception as e:
                print(f"⚠️ Nahrávání vypnuto: {e}")
                self.recorder = None

        # V režimu 'meet' hlavní záznam = klient (BlackHole). Volitelně navíc
        # zaznamenáme MŮJ hlas z mikrofonu do zvláštního souboru _ja.ogg.
        self.mic_audio = None
        self.mic_recorder = None
        if (self.mode == "meet" and RECORDER_AVAILABLE
                and rec_cfg.get("enabled") and rec_cfg.get("record_my_voice")):
            try:
                mic_dev = resolve_input_device(rec_cfg.get("my_voice_device"))
                self.mic_audio = AudioCapture(
                    sample_rate=audio_cfg["sample_rate"],
                    chunk_duration_ms=audio_cfg["chunk_duration_ms"],
                    input_device=mic_dev,
                )
                self.mic_recorder = AudioRecorder(
                    output_dir=rec_cfg.get("output_dir", "recordings"),
                    sample_rate=audio_cfg["sample_rate"],
                    fmt=rec_cfg.get("format", "OGG"),
                    session_stamp=self._session_stamp,
                    label="ja",
                )
                mic_name = (sd.query_devices(mic_dev)["name"] if mic_dev is not None
                            else sd.query_devices(kind="input")["name"])
                print(f"🎙️  Můj hlas se nahrává zvlášť z: {mic_name}")
            except Exception as e:
                print(f"⚠️ Záznam mého hlasu vypnut: {e}")
                self.mic_audio = None
                self.mic_recorder = None

        # Auto-routing + monitor: jen v režimu 'meet' (systémový zvuk → BlackHole)
        self.monitor = None
        if self.mode == "meet" and MONITOR_AVAILABLE:
            self.monitor = AudioMonitor(
                sample_rate=audio_cfg["sample_rate"],
                blackhole_name=modes["meet"].get("device", "BlackHole"),
                monitor_device=self._monitor_device,
            )

        # Role určuje system prompt (obchodník / kouč / pm …)
        roles = self.config.get("roles", {})
        self.role = role or self.config.get("default_role", "obchodnik")
        if self.role not in roles:
            raise ValueError(
                f"Neznámá role '{self.role}'. Dostupné: {', '.join(roles) or '(žádné v configu)'}"
            )
        role_cfg = roles.get(self.role, {})
        print(f"🎭 Role '{self.role}' — {role_cfg.get('popis', '')}")

        # Textový přepis konverzace (stejný název jako audio nahrávka).
        # Až tady — potřebuje self.role i self.mode.
        self.transcript_logger = None
        if rec_cfg.get("save_transcript"):
            try:
                self.transcript_logger = TranscriptLogger(
                    output_dir=rec_cfg.get("output_dir") or "~/Documents/Menthol-recordings",
                    session_stamp=self._session_stamp,
                    mode=self.mode,
                    role=self.role,
                )
            except Exception as e:
                print(f"⚠️ Ukládání přepisu vypnuto: {e}")

        api_keys = self.config.get("api_keys", {})

        def build_chain(priority: list) -> list:
            return [
                {
                    "provider": entry["provider"],
                    "model": entry["model"],
                    "api_key": api_keys.get(entry["provider"]),
                }
                for entry in priority
            ]

        llm_chain = build_chain(self.config["llm"]["priority"])

        try:
            self.llm = LLMHandler(
                providers=llm_chain,
                timeout_seconds=self.config["system"]["llm_timeout_seconds"],
                system_prompt=role_cfg.get("system_prompt"),
            )
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

        # Proaktivní upozornění (volitelné) — klasifikuje každou finální větu
        # na pozadí a při triggeru pošle macOS notifikaci.
        self.trigger_classifier = None
        alerts_cfg = self.config.get("alerts", {})
        if alerts_cfg.get("enabled"):
            alerts_chain = build_chain(alerts_cfg.get("priority", self.config["llm"]["priority"]))
            self.trigger_classifier = TriggerClassifier(
                providers=alerts_chain,
                cooldown_seconds=alerts_cfg.get("cooldown_seconds", 20),
                sound=alerts_cfg.get("notification_sound", False),
                overlay_duration=alerts_cfg.get("notification_duration", 3),
                notification_type=alerts_cfg.get("notification_type", "overlay"),
                overlay_func=self.overlay_func,
            )
            chain_desc = " → ".join(f"{e['provider']}/{e['model']}" for e in alerts_chain)
            print(
                f"🔔 Upozornění zapnutá — {chain_desc} "
                f"(cooldown {alerts_cfg.get('cooldown_seconds', 20)}s)"
            )

        # Hotkey listener — nativní Carbon (bez pynputu, bez Input Monitoring).
        print("⏳ Načítám hotkey (Carbon)…")
        from src.hotkey_native import HotkeyListener
        self.hotkey = HotkeyListener(
            key_combination=self.config["hotkey"]["key_combination"],
            callback=self.on_hotkey_pressed,
        )

        # State
        self._last_transcript = ""
        self._full_transcript = []  # akumulovaný textový přepis (seznam úseků)
        self._last_interim = ""     # rozpracovaná (nefinalizovaná) věta
        self._transcript_lock = Lock()
        self._is_running = False
        self._getting_suggestion = False
        self._transcription_thread = None
        self._stop_event = Event()
        self._stopped = False  # guard proti dvojímu ukončení
        self._interim_lines = 0  # kolik řádků zabírá vykreslený interim blok


    def on_hotkey_pressed(self):
        """Called when hotkey is pressed."""
        print("\n🔔 HOTKEY PRESSED!")
        if self._getting_suggestion:
            print("⚠️ Already processing suggestion, skipping")
            return  # Already processing

        self._getting_suggestion = True
        print("💡 Generuji nápovědu...")

        try:
            # Použij akumulovaný přepis + aktuálně rozpracovanou větu
            # (žádný nový přepis audia)
            with self._transcript_lock:
                parts = list(self._full_transcript)
                if self._last_interim:
                    parts.append(self._last_interim)
                context_text = " ".join(parts).strip()

            if context_text:
                # Do LLM jde POUZE text (posledních 5 vět), označený mluvčím.
                # Pokud jsou v hovoru kolegové/partneři (ne klient), řekni to
                # modelu explicitně, ať jejich repliky nebere jako signál klienta.
                llm_context = (
                    "V hovoru jsou i tito účastníci, kteří NEJSOU klient (jsou "
                    "to kolegové/obchodní partneři) — jejich vyjádření neber "
                    "jako potřeby nebo námitky klienta: " + ", ".join(self.internal_speakers)
                ) if self.internal_speakers else ""
                suggestion = self.llm.get_suggestion(
                    context_text, context=llm_context, speaker=self.speaker
                )
                self._print_suggestion(suggestion)
                if self.transcript_logger:
                    self.transcript_logger.log_suggestion(suggestion)
            else:
                print("⚠️ Zatím nemám žádný přepis — řekni nejdřív pár vět.")

        except Exception as e:
            self.ui.update_suggestion(f"Error: {str(e)[:60]}")
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._getting_suggestion = False
            print("🎤 Ready for next suggestion")

    def _print_suggestion(self, text: str):
        """Vypíše nápovědu ve zvýrazněném barevném rámečku."""
        # Haiku občas obalí odpověď uvozovkami — pryč s nimi
        text = text.strip().strip('"').strip("„").strip("“").strip()

        # Menubar app: nápověda jde na obrazovku (overlay), ne do terminálu.
        if self.on_suggestion:
            try:
                self.on_suggestion(text)
            except Exception as e:
                print(f"[SUGGEST] overlay selhal: {e}")
            return

        width = self.config["ui"].get("width", 60)
        cyan = "\033[96m"        # rámeček
        highlight = "\033[1;93m"  # tučná žlutá = samotná rada
        reset = "\033[0m"

        lines = textwrap.wrap(text, width=width - 4) or [""]
        top = f"{cyan}╭─ 💡 NÁPOVĚDA {'─' * max(0, width - 16)}╮{reset}"
        bottom = f"{cyan}╰{'─' * (width - 2)}╯{reset}"

        self._clear_interim()
        print(top)
        for line in lines:
            pad = " " * max(0, width - 4 - len(line))
            print(f"{cyan}│{reset} {highlight}{line}{reset}{pad} {cyan}│{reset}")
        print(bottom + "\n")

    def _on_meta(self, title: str, code: str = None):
        """Callback z extension: název meetingu (titulek tabu) + kód z URL.
        Titulek má přednost; když z něj po očištění nic nezbude, použije se kód."""
        if not self.transcript_logger:
            return
        prev = self.transcript_logger.meeting_name
        self.transcript_logger.set_meeting_name(title)
        if not self.transcript_logger.meeting_name and code:
            self.transcript_logger.set_meeting_name(code)
        if self.transcript_logger.meeting_name != prev:
            print(f"[META] název meetingu: {self.transcript_logger.meeting_name!r} "
                  f"(title={title!r}, code={code!r})")

    def _on_final_transcript(self, text: str, speaker: Optional[str] = None):
        """Callback streamingu: hotový úsek → přidej do přepisu.

        speaker: přebije self.speaker, když ho pošle zdroj sám (titulky Meet
        posílají jméno mluvčího přímo z UI — přesnější než statický config).
        """
        effective_speaker = speaker if speaker is not None else self.speaker
        # Jméno mluvčího jde i do přepisu pro LLM — jinak model neví, kdo co
        # řekl, a v captions módu s víc mluvčími si domýšlí, že mluví klient.
        entry = f"{effective_speaker}: {text}" if effective_speaker else text
        with self._transcript_lock:
            self._full_transcript.append(entry)
            self._last_interim = ""  # finalizováno → rozpracovaná věta je hotová
            max_chunks = self.config["system"].get("max_transcript_chunks", 60)
            if len(self._full_transcript) > max_chunks:
                self._full_transcript = self._full_transcript[-max_chunks:]
            recent_context = " ".join(self._full_transcript[-6:])
        self._last_transcript = text
        # Nejdřív smaž blok průběžného textu, ať se finál nevykreslí přes něj
        self._clear_interim()
        # Zalom dlouhý monolog čitelně, další řádky odsaď pod prefix "📝 "
        width = shutil.get_terminal_size((100, 24)).columns
        prefix = f"📝 {effective_speaker}: " if effective_speaker else "📝 "
        wrapped = textwrap.fill(
            text,
            width=max(40, width - 2),
            initial_indent=prefix,
            subsequent_indent="   ",
        )
        print(wrapped)

        # Zapiš do textového přepisu (s označením mluvčího)
        if self.transcript_logger:
            self.transcript_logger.log_transcript(text, speaker=effective_speaker)

        # Proaktivní upozornění na pozadí (neblokuje zpracování přepisu).
        # Vynech věty od kolegy/partnera — nejsou signál od klienta.
        if self.trigger_classifier and effective_speaker not in self.internal_speakers:
            self.trigger_classifier.check_async(recent_context, speaker=effective_speaker)

    def _clear_interim(self):
        """Smaže celý blok průběžného textu (i víceřádkový).

        \\r\\033[K umí smazat jen aktuální řádek, proto se u víceřádkového
        bloku musíme kurzorem vrátit nahoru (\\033[A) a mazat řádek po řádku.
        """
        print("\r\033[K", end="")
        for _ in range(max(0, self._interim_lines - 1)):
            print("\033[A\033[K", end="")
        self._interim_lines = 0

    def _on_interim_transcript(self, text: str, speaker: Optional[str] = None):
        """Callback streamingu: průběžný text během mluvení.

        Vykreslí se jako blok o max. N řádcích (poslední část toho, co se
        právě říká), který se při každé aktualizaci celý přemaže.
        """
        # Ulož rozpracovanou větu — ať ji nápověda použije, i když ještě
        # není finalizovaná (stisk hotkey uprostřed klientovy věty)
        self._last_interim = text

        if not self.show_interim:
            return

        width = shutil.get_terminal_size((100, 24)).columns
        max_lines = self.config["ui"].get("interim_lines", 3)

        lines = textwrap.wrap(text, width=max(40, width - 3)) or [""]
        lines = lines[-max_lines:]  # ukazuj nejnovější část

        self._clear_interim()
        block = "\n".join(
            (f"\033[90m… {ln}\033[0m" if i == 0 else f"\033[90m  {ln}\033[0m")
            for i, ln in enumerate(lines)
        )
        print(block, end="", flush=True)
        self._interim_lines = len(lines)

    def _is_silence(self, audio_data) -> bool:
        """Vrátí True, když okno obsahuje jen ticho (nízké RMS) → přeskočíme přepis."""
        if audio_data is None or len(audio_data) == 0:
            return True
        rms = float(np.sqrt(np.mean(np.square(audio_data))))
        threshold = self.config["system"].get("silence_rms_threshold", 0.01)
        return rms < threshold

    def _transcription_loop(self):
        """Background thread: přepisuje navazující úseky audia a skládá je
        do souvislého textového přepisu (self._full_transcript)."""
        # Délka jednoho úseku – nepřekrývají se, takže se dají skládat za sebe
        chunk_seconds = self.config["system"].get("chunk_seconds", 5)
        max_chunks = self.config["system"].get("max_transcript_chunks", 60)
        last_chunk_time = time.time()

        while self._is_running and not self._stop_event.is_set():
            try:
                elapsed = time.time() - last_chunk_time
                if elapsed < chunk_seconds:
                    time.sleep(0.1)
                    continue

                # Vezmi audio přesně za dobu od posledního úseku (+malý přesah)
                audio_data = self.audio.get_audio_buffer(
                    duration_seconds=int(elapsed) + 1
                )
                last_chunk_time = time.time()

                # Přeskoč ticho — ať zbytečně nevoláme přepis (šetří kvótu)
                if len(audio_data) == 0 or self._is_silence(audio_data):
                    continue

                transcript = self.transcriber.transcribe_partial(audio_data)
                if transcript:
                    with self._transcript_lock:
                        self._full_transcript.append(transcript)
                        # Drž jen posledních N úseků (šetří paměť)
                        if len(self._full_transcript) > max_chunks:
                            self._full_transcript = self._full_transcript[-max_chunks:]
                    self._last_transcript = transcript
                    print(f"📝 {transcript}")
                    if self.transcript_logger:
                        self.transcript_logger.log_transcript(
                            transcript, speaker=self.speaker
                        )

            except Exception as e:
                print(f"[TRANS] Error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)

    def start_services(self):
        """Spustí všechny služby (Meet, hotkey, transcriber) BEZ blokující
        smyčky. Vhodné pro běh pod cizím runloopem (menubar app). CLI použije
        run(), který navíc nainstaluje signal handlery a blokuje do Ctrl+C."""
        print("🌿 Menthol — spouštím...")
        llm_chain_desc = " → ".join(f"{e['provider']}/{e['model']}" for e in self.llm.providers)
        print(f"💡 Model pro nápovědu (hotkey): {llm_chain_desc}")

        self._is_running = True
        self._stop_event.clear()

        # Captions mode: otevři Meet v NORMÁLNÍM Brave okně (ne PWA "app" okno —
        # to neinjektuje content script rozšíření, takže titulky nikdo nečte).
        # Jen dashboard, k hovoru se uživatel připojí sám ručně.
        if self.meet_app_path:
            try:
                cmd = ["open", "-a", self.meet_app_path]
                if self.meet_url:
                    cmd.append(self.meet_url)
                subprocess.Popen(cmd)
                print(f"🌐 Otevírám Meet: {os.path.basename(self.meet_app_path)}")
            except Exception as e:
                print(f"⚠️ Nepodařilo se otevřít Meet appku: {e}")

        # Režim meet: přepni systémový výstup na BlackHole PŘED startem capture,
        # ať Meet hraje rovnou do virtuálního kabelu
        if self.monitor:
            self.monitor.route_system_to_blackhole()

        # Start audio capture (captions mode nemá audio zdroj)
        if self.audio:
            self.audio.start()
            print("✓ Audio capture started")

        # Start hotkey listener
        self.hotkey.start()

        # Nahrávání hovoru (vlastní odběr proudu)
        if self.recorder:
            self.recorder.start(self.audio.subscribe())

        # Paralelní záznam mého hlasu z mikrofonu (režim meet)
        if self.mic_audio and self.mic_recorder:
            self.mic_audio.start()
            self.mic_recorder.start(self.mic_audio.subscribe())

        # Monitor: přehrává zachycený zvuk do fyzického výstupu (aby bylo slyšet)
        if self.monitor:
            self.monitor.start_monitor(self.audio.subscribe())

        if self.streaming:
            # Streaming: výsledky chodí callbackem, žádná polling smyčka
            self.transcriber.start(self.audio.subscribe() if self.audio else None)
        else:
            # Batch: přepis se tahá v pravidelné smyčce
            self._transcription_thread = Thread(
                target=self._transcription_loop,
                daemon=True,
            )
            self._transcription_thread.start()

        # Skip UI render - just log
        hotkey_label = self.config["hotkey"]["key_combination"].upper()
        print("\n" + "="*60)
        print(f"🎤 POSLOUCHÁM — zmáčkni {hotkey_label} pro nápovědu")
        print("="*60 + "\n")

    def run(self):
        """CLI vstup: nainstaluje signal handlery, spustí služby a blokuje
        do Ctrl+C."""
        self.install_signal_handlers()
        self.start_services()
        try:
            # Keep running until Ctrl+C
            while self._is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nShutting down...")
            self.stop()

    def stop(self):
        """Zastaví aplikaci. Idempotentní — bezpečné volat opakovaně
        (Ctrl+C, SIGTERM i atexit můžou dorazit současně)."""
        if self._stopped:
            return
        self._stopped = True

        self._is_running = False
        self._stop_event.set()

        # Pořadí: nejdřív odstřihni zdroje událostí, pak dopiš soubory
        try:
            self.hotkey.stop()
        except Exception:
            pass

        if self.streaming:
            try:
                self.transcriber.stop()  # ukončí generátor → zavře gRPC stream
            except Exception as e:
                print(f"[STOP] Chyba při zavírání streamu: {e}")

        # Monitor + vrácení systémového výstupu (důležité: vždy obnovit!)
        if self.monitor:
            try:
                self.monitor.stop()
            except Exception as e:
                print(f"[STOP] Chyba monitoru: {e}")

        if self.recorder:
            try:
                self.recorder.stop()  # dopíše a uzavře OGG
            except Exception as e:
                print(f"[STOP] Chyba při uzavírání nahrávky: {e}")

        # Záznam mého hlasu (mikrofon)
        if self.mic_recorder:
            try:
                self.mic_recorder.stop()
            except Exception as e:
                print(f"[STOP] Chyba při uzavírání záznamu mého hlasu: {e}")
        if self.mic_audio:
            try:
                self.mic_audio.cleanup()
            except Exception:
                pass

        # Souhrn spotřeby Google STT (odeslaný audio čas → odhad ceny)
        seconds = float(getattr(self.transcriber, "audio_seconds_sent", 0.0))
        usage_line = None
        if seconds > 0:
            usage_line = format_usage(seconds, self.config.get("pricing", {}))
            free = self.config.get("pricing", {}).get("free_minutes_per_month", 0)
            print("\n" + "─" * 60)
            print(f"📊 {usage_line}")
            if free:
                print(f"   (prvních {free} min/měsíc je u Googlu zdarma)")
            print("─" * 60)

        # Uzavři textový přepis se souhrnem spotřeby.
        # (Poslední nedokončenou větu commitne sám transcriber přes on_final
        #  při zastavení streamu — viz _run/_pending_interim.)
        if self.transcript_logger:
            try:
                self.transcript_logger.close(usage=usage_line)
            except Exception as e:
                print(f"[STOP] Chyba při uzavírání přepisu: {e}")

        if self.audio:
            try:
                self.audio.cleanup()
            except Exception:
                pass

        if self._transcription_thread:
            self._transcription_thread.join(timeout=2)

        print("✓ Application stopped")

    def install_signal_handlers(self):
        """Zajistí čisté ukončení i při SIGTERM (pkill) a SIGINT."""
        def handler(signum, frame):
            print(f"\n\nDostal jsem signál {signum}, ukončuji...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
        # Záchranná síť pro běžný pád/exit
        atexit.register(self.stop)


def _load_config_for_help(argv):
    """Načte config (kvůli výpisu rolí/režimů v --help). Toleruje chyby."""
    cfg_path = "config.json"
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            cfg_path = argv[i + 1]
    try:
        return load_config(cfg_path)
    except Exception:
        return {}


def _build_epilog(cfg):
    """Sestaví nápovědný text s režimy, rolemi a příklady z configu."""
    lines = []
    modes = cfg.get("audio", {}).get("modes", {})
    if modes:
        lines.append("Režimy (--mode):")
        for name, m in modes.items():
            lines.append(f"  {name:10} {m.get('popis', '')}")
        lines.append("")
    roles = cfg.get("roles", {})
    if roles:
        lines.append("Role (--role) — definuj vlastní v config.json → roles:")
        for name, r in roles.items():
            lines.append(f"  {name:10} {r.get('popis', '')}")
        lines.append("")
    lines += [
        "Příklady:",
        "  python -m src.main --mode meet --role obchodnik",
        "  python -m src.main --mode mobil --role kouc",
        "  python -m src.main --mode meet --monitor AirPods",
        "  python -m src.main --list-devices",
        "",
        "Ukončení: Ctrl+C (vrátí systémový výstup, dopíše nahrávku).",
    ]
    return "\n".join(lines)


def main():
    cfg = _load_config_for_help(sys.argv[1:])
    role_choices = list(cfg.get("roles", {}).keys()) or None
    mode_choices = list(cfg.get("audio", {}).get("modes", {}).keys()) or ["mobil", "meet"]

    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="🌿 Menthol — realtime našeptávač do hovoru: přepis řeči + nápověda co říct (Cmd+Shift+H).",
        epilog=_build_epilog(cfg),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Cesta ke konfiguračnímu souboru (výchozí: config.json)",
    )
    parser.add_argument(
        "--mode", "-m", choices=mode_choices, default=None,
        help="Zdroj zvuku (viz Režimy níže). Výchozí podle config.json.",
    )
    parser.add_argument(
        "--role", "-r", choices=role_choices, default=None,
        help="Osobnost rádce (viz Role níže). Výchozí podle config.json.",
    )
    parser.add_argument(
        "--monitor", default=None,
        help=(
            "Kam přehrávat zvuk, ať slyšíš (režim meet). Část názvu zařízení, "
            "např. 'MacBook' nebo 'AirPods'. Výchozí = kde jsi poslouchal, "
            "s auto-přepnutím na připojená sluchátka."
        ),
    )
    parser.add_argument(
        "--list-devices", action="store_true",
        help="Vypíše dostupná audio zařízení a skončí",
    )
    parser.add_argument(
        "--internal-speaker", action="append", default=None, metavar="JMÉNO",
        help=(
            "Jméno účastníka (přesně jak ho ukazují Meet titulky), který NENÍ "
            "klient — kolega/obchodní partner. Jde přidat opakovaně. Doplní se "
            "k jménům z config.json (internal_speakers), funguje jen v captions módu."
        ),
    )
    args = parser.parse_args()

    if args.list_devices:
        if not AUDIO_AVAILABLE:
            print("❌ Výpis zařízení vyžaduje sounddevice (jen v audio buildu).")
            return
        print("=== VSTUPNÍ zařízení ===")
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"  {i:2}  {d['name']}")
        print("=== VÝSTUPNÍ zařízení (pro --monitor) ===")
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                print(f"  {i:2}  {d['name']}")
        return

    app = RealtimeAssistant(config_path=args.config, mode=args.mode,
                            monitor_device=args.monitor, role=args.role,
                            internal_speakers=args.internal_speaker)
    app.run()


if __name__ == "__main__":
    main()
