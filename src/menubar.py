"""Menubar (rumps) shell pro Menthol — captions režim.

Nahrazuje terminál: appka žije v horní liště. Odtud se spouští/zastavuje
poslech Meet titulků, přepíná role, otevírá Meet a nastavují API klíče
(ukládají se do macOS Keychain). Nápověda z hotkey (Cmd+Shift+H) se zobrazuje
jako overlay uprostřed obrazovky, ne v terminálu.
"""
import os
import sys
import json
import time
import subprocess

# --- cesty (fungují v repu i uvnitř .app bundlu) ---
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SRC_DIR)
sys.path.insert(0, APP_DIR)  # ať jde `from src... import`, nezávisle na CWD

USER_DIR = os.path.expanduser("~/Library/Application Support/Menthol")
LOG_DIR = os.path.expanduser("~/Library/Logs/Menthol")
USER_CONFIG = os.path.join(USER_DIR, "config.json")
# py2app kopíruje config.example.json do Contents/Resources a nastaví RESOURCEPATH.
# V repu (vývoj) leží vedle src/, tedy v APP_DIR.
_RES = os.environ.get("RESOURCEPATH")
EXAMPLE_CONFIG = (
    os.path.join(_RES, "config.example.json") if _RES
    else os.path.join(APP_DIR, "config.example.json")
)


def _ensure_dirs():
    os.makedirs(USER_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(os.path.join(USER_DIR, "recordings"), exist_ok=True)


def _redirect_logs():
    """Appka nemá terminál — veškerý stdout/stderr jde do logu, ať jde ladit."""
    # UTF-8 nutné: v py2app bundlu je default kódování často ASCII a print("🌿…")
    # by spadl na UnicodeEncodeError. errors="replace" je pojistka.
    log = open(os.path.join(LOG_DIR, "menthol.log"), "a", buffering=1,
               encoding="utf-8", errors="replace")
    sys.stdout = log
    sys.stderr = log


def _seed_config():
    """Při prvním spuštění zkopíruje vzorový config do Application Support."""
    if not os.path.exists(USER_CONFIG) and os.path.exists(EXAMPLE_CONFIG):
        import shutil
        shutil.copyfile(EXAMPLE_CONFIG, USER_CONFIG)


import rumps  # noqa: E402
from src import keychain  # noqa: E402
from src import overlay  # noqa: E402
from src.config import load_config  # noqa: E402


class MentholApp(rumps.App):
    def __init__(self):
        super().__init__("🌿", quit_button=None)
        self.assistant = None
        self.running = False

        cfg = load_config(USER_CONFIG)
        self.roles = cfg.get("roles", {}) or {"obchodnik": {"popis": "Obchodník"}}
        self.role = cfg.get("default_role") or next(iter(self.roles))
        self.hotkey_combo = cfg.get("hotkey", {}).get("key_combination", "cmd+shift+h")

        self._build_menu()

        # Hlídač: když z Meetu přestane chodit heartbeat (zavřený tab, položený
        # hovor, odchod ze schůzky), po ~15 s sám zastav poslech.
        self._watchdog = rumps.Timer(self._on_watchdog, 5)
        self._watchdog.start()

    # ---- menu ----
    def _build_menu(self):
        self.status_item = rumps.MenuItem("● Zastaveno")
        self.status_item.set_callback(None)  # jen text, neklikatelné

        self.toggle_item = rumps.MenuItem("Spustit poslech", callback=self.toggle)
        self.meet_item = rumps.MenuItem("Otevřít Google Meet", callback=self.open_meet)

        role_menu = rumps.MenuItem("Role rádce")
        self.role_items = {}
        for name, r in self.roles.items():
            it = rumps.MenuItem(r.get("popis", name), callback=self._role_cb(name))
            it.state = 1 if name == self.role else 0
            self.role_items[name] = it
            role_menu.add(it)

        self.hotkey_item = rumps.MenuItem(
            f"Zkratka: {self.hotkey_combo} (změnit…)", callback=self.set_hotkey
        )

        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.meet_item,
            role_menu,
            self.hotkey_item,
            None,
            rumps.MenuItem("Otevřít složku přepisů", callback=self.open_recordings),
            rumps.MenuItem("Změnit složku přepisů…", callback=self.set_output_dir),
            None,
            rumps.MenuItem("Nastavit Anthropic klíč…", callback=self.set_anthropic),
            rumps.MenuItem("Nastavit Gemini klíč (volitelné)…", callback=self.set_gemini),
            None,
            rumps.MenuItem("Ukončit Menthol", callback=self.quit_app),
        ]

    def _role_cb(self, name):
        def cb(_):
            self.set_role(name)
        return cb

    # ---- akce ----
    def toggle(self, _):
        self.stop() if self.running else self.start()

    def start(self):
        keychain.load_into_env()
        if not keychain.has_key("anthropic"):
            self.set_anthropic(None)
            keychain.load_into_env()
            if not keychain.has_key("anthropic"):
                rumps.alert("Menthol", "Bez Anthropic klíče poslech nespustím.")
                return
        try:
            from src.main import RealtimeAssistant
            self.assistant = RealtimeAssistant(
                config_path=USER_CONFIG,
                mode="captions",
                role=self.role,
                on_suggestion=lambda t: overlay.show(t, 6.0, False),
                overlay_func=lambda t: overlay.show(t, 4.0, False),
            )
            self.assistant.start_services()
            self.running = True
            self._set_status(True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            rumps.alert("Menthol — chyba při startu", str(e)[:400])
            self.assistant = None
            self.running = False
            self._set_status(False)

    def _on_watchdog(self, _timer):
        if not self.running or not self.assistant:
            return
        tr = getattr(self.assistant, "transcriber", None)
        ts = getattr(tr, "last_meta_ts", None)
        if ts is None:
            return  # ještě jsme neviděli žádný heartbeat (meeting nezačal)
        if time.time() - ts > 15:
            print("[MENUBAR] Žádný heartbeat z Meetu >15 s → auto-stop")
            self.stop()
            rumps.notification("Menthol", "", "Poslech zastaven — konec meetingu.")

    def stop(self):
        if self.assistant:
            try:
                self.assistant.stop()
            except Exception:
                import traceback
                traceback.print_exc()
        self.assistant = None
        self.running = False
        self._set_status(False)

    def set_role(self, name):
        self.role = name
        for n, it in self.role_items.items():
            it.state = 1 if n == name else 0
        if self.running:  # přepnutí role za běhu = restart služeb
            self.stop()
            self.start()

    def open_meet(self, _):
        cfg = load_config(USER_CONFIG)
        mode_cfg = cfg.get("audio", {}).get("modes", {}).get("captions", {})
        app = mode_cfg.get("meet_app", "Brave Browser")
        url = mode_cfg.get("meet_url", "https://meet.google.com/")
        cmd = ["open", "-a", app]
        if url:
            cmd.append(url)
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            rumps.alert("Menthol", f"Nepodařilo se otevřít Meet: {e}")

    def _recordings_dir(self):
        cfg = load_config(USER_CONFIG)
        d = cfg.get("recording", {}).get("output_dir") or "~/Documents/Menthol-recordings"
        return os.path.expanduser(d)

    def open_recordings(self, _):
        d = self._recordings_dir()
        os.makedirs(d, exist_ok=True)
        subprocess.Popen(["open", d])

    def set_output_dir(self, _):
        script = ('POSIX path of (choose folder with prompt '
                  '"Kam ukládat přepisy hovorů?")')
        try:
            out = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True)
        except Exception as e:
            rumps.alert("Menthol", f"Výběr složky selhal: {e}")
            return
        path = (out.stdout or "").strip().rstrip("/")
        if not path:  # uživatel dal Zrušit
            return
        self._save_config({"recording": {"output_dir": path}})
        rumps.notification("Menthol", "", f"Přepisy → {path}")
        if self.running:
            self.stop()
            self.start()

    def set_hotkey(self, _):
        from src.hotkey_native import parse_combo
        win = rumps.Window(
            title="Menthol — klávesová zkratka",
            message=(
                "Napiš zkratku, např.  cmd+shift+h  nebo  f9  nebo  ctrl+option+m.\n"
                "Vyhni se běžným zkratkám (cmd+c, cmd+x, cmd+v) — Menthol je "
                "'spotřebuje' a přestaly by fungovat všude."
            ),
            default_text=self.hotkey_combo,
            ok="Uložit",
            cancel="Zrušit",
            dimensions=(220, 24),
        )
        resp = win.run()
        if not (resp.clicked and resp.text.strip()):
            return
        combo = resp.text.strip().lower()
        keycode, _mods = parse_combo(combo)
        if keycode is None:
            rumps.alert("Menthol", f"Nerozpoznal jsem klávesu ve '{combo}'.")
            return
        self.hotkey_combo = combo
        self._save_config({"hotkey": {"key_combination": combo}})
        self.hotkey_item.title = f"Zkratka: {combo} (změnit…)"
        if self.running:  # aplikuj hned
            self.stop()
            self.start()
        else:
            rumps.notification("Menthol", "", f"Zkratka nastavena: {combo}")

    def _save_config(self, patch: dict):
        """Zapíše dílčí změnu do uživatelského config.json (merge na 1. úrovni)."""
        try:
            cfg = load_config(USER_CONFIG)
        except Exception:
            cfg = {}
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

    def set_anthropic(self, _):
        self._prompt_key("anthropic", "Anthropic API klíč (povinný)")

    def set_gemini(self, _):
        self._prompt_key("gemini", "Gemini API klíč (volitelné, rychlejší nápovědy)")

    def _prompt_key(self, name, label):
        win = rumps.Window(
            title="Menthol — API klíč",
            message=f"{label}.\nUloží se bezpečně do macOS Keychain, ne do souboru.",
            ok="Uložit",
            cancel="Zrušit",
            secure=True,
            dimensions=(320, 24),
        )
        resp = win.run()
        if resp.clicked and resp.text.strip():
            keychain.set_key(name, resp.text)
            keychain.load_into_env()
            rumps.notification("Menthol", "", f"{name} klíč uložen.")

    def _set_status(self, on):
        self.status_item.title = "● Poslouchám" if on else "● Zastaveno"
        self.toggle_item.title = "Zastavit poslech" if on else "Spustit poslech"
        self.title = "🌿▶" if on else "🌿"

    def quit_app(self, _):
        self.stop()
        rumps.quit_application()


def main():
    _ensure_dirs()
    _redirect_logs()
    _seed_config()
    os.chdir(USER_DIR)  # přepisy (přepis hovoru) ať jdou do user složky
    MentholApp().run()


if __name__ == "__main__":
    main()
