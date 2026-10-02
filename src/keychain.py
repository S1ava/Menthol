"""Uložení a čtení API klíčů do chráněného souboru (jen pro tvůj účet).

POZN: Původně přes macOS Keychain, ale ad-hoc podepsaná appka nemá stabilní
identitu, takže se Keychain ptal na heslo u každého přístupu (a po každém
rebuildu znovu). Proto klíče držíme v `secrets.json` s právy 0600 v
~/Library/Application Support/Menthol/ — čte je jen tvůj uživatel, nejsou v
repozitáři ani v bundlu appky. Interface (get/set/has/load_into_env) zůstává.
"""
import os
import json

SECRETS = os.path.expanduser(
    "~/Library/Application Support/Menthol/secrets.json"
)

# Mapování interního jména → env proměnná, kterou čte LLMHandler/TriggerClassifier.
ENV_NAMES = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _read() -> dict:
    try:
        with open(SECRETS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data: dict):
    os.makedirs(os.path.dirname(SECRETS), exist_ok=True)
    # Zapiš s právy 0600 (rw jen vlastník).
    fd = os.open(SECRETS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def get_key(name: str) -> str:
    return (_read().get(name) or "").strip()


def set_key(name: str, value: str):
    data = _read()
    value = (value or "").strip()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    _write(data)


def has_key(name: str) -> bool:
    return bool(get_key(name))


def load_into_env():
    """Načte klíče ze souboru do os.environ (fallback čte LLMHandler)."""
    data = _read()
    for name, env in ENV_NAMES.items():
        val = (data.get(name) or "").strip()
        if val:
            os.environ[env] = val
