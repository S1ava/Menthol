"""Menubar (rumps) shell pro Menthol — captions režim.

Appka žije v horní liště. Odtud se spouští/zastavuje poslech Meet titulků;
veškerá nastavení jsou pod podmenu „Nastavení". Nápověda z hotkey se zobrazuje
jako overlay uprostřed obrazovky. API klíče jsou v chráněném souboru (ne v repu).
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
_RES = os.environ.get("RESOURCEPATH")  # py2app → Contents/Resources
EXAMPLE_CONFIG = (
    os.path.join(_RES, "config.example.json") if _RES
    else os.path.join(APP_DIR, "config.example.json")
)

# Volby prohlížeče: popisek → hodnota do config (meet_app).
# Jen prohlížeče, kde běží naše rozšíření (Chromium). Safari a samostatná
# Meet.app (PWA) rozšíření nenačtou → titulky by nefungovaly, proto tu nejsou.
BROWSERS = [
    ("Brave", "Brave Browser"),
    ("Chrome", "Google Chrome"),
]
# Volby AI: popisek → ai.mode.
AI_MODES = [
    ("Claude (Anthropic)", "anthropic"),
    ("Gemini (Google)", "gemini"),
    ("Nic neposílat (bez rad)", "none"),
]


def _ensure_dirs():
    os.makedirs(USER_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def _redirect_logs():
    """Appka nemá terminál — stdout/stderr do logu (UTF-8 kvůli emoji/češtině)."""
    log = open(os.path.join(LOG_DIR, "menthol.log"), "a", buffering=1,
               encoding="utf-8", errors="replace")
    sys.stdout = log
    sys.stderr = log


def _seed_config():
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
        self.cc_hotkey_combo = cfg.get("hotkey", {}).get("captions_toggle", "cmd+shift+j")
        self.ai_mode = (cfg.get("ai", {}) or {}).get("mode", "anthropic")
        cap = cfg.get("audio", {}).get("modes", {}).get("captions", {})
        self.meet_browser = cap.get("meet_app", "Brave Browser")
        self.open_after = bool(cfg.get("recording", {}).get("open_folder_after", False))

        self._build_menu()

        # Hlídač: když z Meetu přestane chodit heartbeat (zavřený tab, položený
        # hovor, odchod ze schůzky), po ~15 s sám zastav poslech.
        self._watchdog = rumps.Timer(self._on_watchdog, 5)
        self._watchdog.start()

    # ---- stavba menu ----
    def _build_menu(self):
        self.status_item = rumps.MenuItem("● Zastaveno")
        self.status_item.set_callback(None)
        self.toggle_item = rumps.MenuItem("Spustit poslech", callback=self.toggle)
        self.meet_item = rumps.MenuItem("Otevřít Google Meet", callback=self.open_meet)

        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.meet_item,
            None,
            self._settings_menu(),
            None,
            rumps.MenuItem("Ukončit Menthol", callback=self.quit_app),
        ]

    def _settings_menu(self):
        settings = rumps.MenuItem("Nastavení")

        # Role
        role_menu = rumps.MenuItem("Role rádce")
        self.role_items = {}
        for name, r in self.roles.items():
            it = rumps.MenuItem(r.get("popis", name), callback=self._role_cb(name))
            it.state = 1 if name == self.role else 0
            self.role_items[name] = it
            role_menu.add(it)
        role_menu.add(rumps.separator)
        role_menu.add(rumps.MenuItem("Upravit prompt role…", callback=self.edit_role_prompt))
        role_menu.add(rumps.MenuItem("Přejmenovat roli…", callback=self.rename_role))
        role_menu.add(rumps.MenuItem("Přidat novou roli…", callback=self.add_role))
        role_menu.add(rumps.MenuItem("Upravit config.json (pokročilé)…", callback=self.open_config))
        settings.add(role_menu)

        # Prohlížeč pro Meet
        br_menu = rumps.MenuItem("Prohlížeč pro Meet")
        self.browser_items = {}
        for label, val in BROWSERS:
            it = rumps.MenuItem(label, callback=self._browser_cb(val))
            it.state = 1 if val == self.meet_browser else 0
            self.browser_items[val] = it
            br_menu.add(it)
        settings.add(br_menu)

        # AI / nápověda
        ai_menu = rumps.MenuItem("AI / nápověda")
        self.ai_items = {}
        for label, mode in AI_MODES:
            it = rumps.MenuItem(label, callback=self._ai_cb(mode))
            it.state = 1 if mode == self.ai_mode else 0
            self.ai_items[mode] = it
            ai_menu.add(it)
        ai_menu.add(rumps.separator)
        ai_menu.add(rumps.MenuItem("Nastavit Anthropic klíč…", callback=self.set_anthropic))
        ai_menu.add(rumps.MenuItem("Nastavit Gemini klíč…", callback=self.set_gemini))
        settings.add(ai_menu)

        # Přepisy
        rec_menu = rumps.MenuItem("Přepisy")
        rec_menu.add(rumps.MenuItem("Otevřít složku přepisů", callback=self.open_recordings))
        rec_menu.add(rumps.MenuItem("Změnit složku přepisů…", callback=self.set_output_dir))
        self.open_after_item = rumps.MenuItem(
            "Po skončení otevřít složku", callback=self.toggle_open_after
        )
        self.open_after_item.state = 1 if self.open_after else 0
        rec_menu.add(self.open_after_item)
        settings.add(rec_menu)

        # Zkratky (rada + překrýt titulky)
        self.hotkey_item = rumps.MenuItem(
            f"Zkratka pro radu: {self.hotkey_combo} (změnit…)", callback=self.set_hotkey
        )
        settings.add(self.hotkey_item)
        self.cc_hotkey_item = rumps.MenuItem(
            f"Zkratka pro titulky: {self.cc_hotkey_combo} (změnit…)",
            callback=self.set_cc_hotkey,
        )
        settings.add(self.cc_hotkey_item)
        return settings

    # ---- callbacky voleb ----
    def _role_cb(self, name):
        return lambda _: self.set_role(name)

    def _browser_cb(self, val):
        return lambda _: self.set_browser(val)

    def _ai_cb(self, mode):
        return lambda _: self.set_ai(mode)

    # ---- běh ----
    def toggle(self, _):
        self.stop(final=True) if self.running else self.start()

    def _required_key(self):
        """Který klíč je potřeba pro aktuální AI režim (nebo None)."""
        return {"anthropic": "anthropic", "gemini": "gemini"}.get(self.ai_mode)

    def start(self):
        keychain.load_into_env()
        need = self._required_key()
        if need and not keychain.has_key(need):
            self._prompt_key(need, f"{need.capitalize()} API klíč")
            keychain.load_into_env()
            if not keychain.has_key(need):
                rumps.alert("Menthol", f"Pro režim '{self.ai_mode}' chybí {need} klíč.")
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
            return
        if time.time() - ts > 15:
            print("[MENUBAR] Žádný heartbeat z Meetu >15 s → auto-stop")
            self.stop(final=True)
            rumps.notification("Menthol", "", "Poslech zastaven — konec meetingu.")

    def stop(self, final=False):
        if self.assistant:
            try:
                self.assistant.stop()
            except Exception:
                import traceback
                traceback.print_exc()
        self.assistant = None
        self.running = False
        self._set_status(False)
        # „Po skončení otevřít složku" jen při reálném konci session (ne při
        # interním restartu kvůli změně nastavení).
        if final and self.open_after:
            self.open_recordings(None)

    def _restart_if_running(self):
        if self.running:
            self.stop(final=False)
            self.start()

    def set_role(self, name):
        self.role = name
        for n, it in self.role_items.items():
            it.state = 1 if n == name else 0
        self._save_config({"default_role": name})
        self._restart_if_running()

    def edit_role_prompt(self, _):
        cfg = load_config(USER_CONFIG)
        roles = cfg.setdefault("roles", {})
        r = roles.setdefault(self.role, {})
        win = rumps.Window(
            title=f"Prompt role: {r.get('popis', self.role)}",
            message="Systémový prompt (instrukce pro AI rádce). Tip: pro delší "
                    "úpravy použij 'Upravit config.json'.",
            default_text=r.get("system_prompt", ""),
            ok="Uložit", cancel="Zrušit", dimensions=(460, 140),
        )
        resp = win.run()
        if not resp.clicked:
            return
        r["system_prompt"] = resp.text
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        rumps.notification("Menthol", "", f"Prompt role '{self.role}' uložen.")
        self._restart_if_running()

    def rename_role(self, _):
        cfg = load_config(USER_CONFIG)
        roles = cfg.setdefault("roles", {})
        r = roles.setdefault(self.role, {})
        win = rumps.Window(
            title="Přejmenovat roli",
            message="Zobrazovaný název role (v menu):",
            default_text=r.get("popis", self.role),
            ok="Uložit", cancel="Zrušit", dimensions=(300, 24),
        )
        resp = win.run()
        if not (resp.clicked and resp.text.strip()):
            return
        r["popis"] = resp.text.strip()
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        if self.role in self.role_items:
            self.role_items[self.role].title = resp.text.strip()

    def add_role(self, _):
        win = rumps.Window(
            title="Přidat novou roli",
            message="Krátký název nové role (např. 'konzultant'):",
            ok="Vytvořit", cancel="Zrušit", dimensions=(240, 24),
        )
        resp = win.run()
        name = (resp.text or "").strip()
        if not (resp.clicked and name):
            return
        cfg = load_config(USER_CONFIG)
        roles = cfg.setdefault("roles", {})
        if name in roles:
            rumps.alert("Menthol", "Role s tímto názvem už existuje.")
            return
        roles[name] = {
            "popis": name,
            "system_prompt": ("Jsi rádce v reálném čase. Na základě přepisu poraď "
                              "krátce (max 1 věta) česky, co teď říct nebo na co se zeptat."),
        }
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        rumps.alert("Menthol", f"Role '{name}' vytvořena. Restartuj Menthol, aby se objevila v menu.")

    def open_config(self, _):
        subprocess.Popen(["open", "-t", USER_CONFIG])

    def set_browser(self, val):
        self.meet_browser = val
        for v, it in self.browser_items.items():
            it.state = 1 if v == val else 0
        # ulož do captions mode
        cfg = load_config(USER_CONFIG)
        cfg.setdefault("audio", {}).setdefault("modes", {}).setdefault("captions", {})["meet_app"] = val
        with open(USER_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

    def set_ai(self, mode):
        self.ai_mode = mode
        for m, it in self.ai_items.items():
            it.state = 1 if m == mode else 0
        self._save_config({"ai": {"mode": mode}})
        self._restart_if_running()

    def toggle_open_after(self, _):
        self.open_after = not self.open_after
        self.open_after_item.state = 1 if self.open_after else 0
        self._save_config({"recording": {"open_folder_after": self.open_after}})

    def open_meet(self, _):
        cfg = load_config(USER_CONFIG)
        cap = cfg.get("audio", {}).get("modes", {}).get("captions", {})
        app = cap.get("meet_app") or "Brave Browser"
        url = cap.get("meet_url", "https://meet.google.com/")
        try:
            subprocess.Popen(["open", "-a", app] + ([url] if url else []))
        except Exception as e:
            rumps.alert("Menthol", f"Nepodařilo se otevřít Meet ({app}): {e}")

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
        if not path:
            return
        self._save_config({"recording": {"output_dir": path}})
        rumps.notification("Menthol", "", f"Přepisy → {path}")

    def set_hotkey(self, _):
        from src.hotkey_native import parse_combo
        win = rumps.Window(
            title="Menthol — zkratka pro radu",
            message=("Napiš zkratku, např.  cmd+shift+h  nebo  f9.\n"
                     "Vyhni se běžným (cmd+c/x/v) — Menthol je 'spotřebuje'."),
            default_text=self.hotkey_combo,
            ok="Uložit", cancel="Zrušit", dimensions=(220, 24),
        )
        resp = win.run()
        if not (resp.clicked and resp.text.strip()):
            return
        combo = resp.text.strip().lower()
        if parse_combo(combo)[0] is None:
            rumps.alert("Menthol", f"Nerozpoznal jsem klávesu ve '{combo}'.")
            return
        self.hotkey_combo = combo
        self._save_config({"hotkey": {"key_combination": combo}})
        self.hotkey_item.title = f"Zkratka pro radu: {combo} (změnit…)"
        self._restart_if_running()
        if not self.running:
            rumps.notification("Menthol", "", f"Zkratka nastavena: {combo}")

    def set_cc_hotkey(self, _):
        from src.hotkey_native import parse_combo
        win = rumps.Window(
            title="Menthol — zkratka pro titulky",
            message="Zkratka pro překrytí/zobrazení titulků v Meetu (např. cmd+shift+j).",
            default_text=self.cc_hotkey_combo,
            ok="Uložit", cancel="Zrušit", dimensions=(220, 24),
        )
        resp = win.run()
        if not (resp.clicked and resp.text.strip()):
            return
        combo = resp.text.strip().lower()
        if parse_combo(combo)[0] is None:
            rumps.alert("Menthol", f"Nerozpoznal jsem klávesu ve '{combo}'.")
            return
        self.cc_hotkey_combo = combo
        self._save_config({"hotkey": {"captions_toggle": combo}})
        self.cc_hotkey_item.title = f"Zkratka pro titulky: {combo} (změnit…)"
        self._restart_if_running()

    def _save_config(self, patch: dict):
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
        self._prompt_key("anthropic", "Anthropic API klíč")

    def set_gemini(self, _):
        self._prompt_key("gemini", "Gemini API klíč")

    def _prompt_key(self, name, label):
        win = rumps.Window(
            title="Menthol — API klíč",
            message=f"{label}.\nUloží se do chráněného souboru jen pro tvůj účet.",
            ok="Uložit", cancel="Zrušit", secure=True, dimensions=(320, 24),
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
        self.stop(final=False)
        rumps.quit_application()


def main():
    _ensure_dirs()
    _redirect_logs()
    _seed_config()
    os.chdir(USER_DIR)
    MentholApp().run()


if __name__ == "__main__":
    main()
