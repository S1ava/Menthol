#!/bin/bash
# =====================================================================
#  Menthol — instalace do Mac appky (captions build, py2app)
#  Interaktivní: ptá se a vysvětluje, co a proč dělá.
#  Bez sudo, bez placeného Apple certifikátu, bez Whisper/BlackHole.
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
BUILDVENV="$SCRIPT_DIR/build-venv"

say()  { printf "\033[96m▶ %s\033[0m\n" "$1"; }
ok()   { printf "\033[92m✓ %s\033[0m\n" "$1"; }
err()  { printf "\033[91m✗ %s\033[0m\n" "$1" >&2; }
ask()  { printf "\033[93m? %s\033[0m " "$1"; }

cat <<'INTRO'
🌿 Menthol — instalace
----------------------
Menthol je appka do horní lišty. Čte titulky Google Meetu a na zkratku ti
poradí, co říct. Tenhle skript:
  1) vytvoří izolované build prostředí (Python venv) a stáhne knihovny,
  2) postaví Menthol.app a nainstaluje ji do Aplikací,
  3) vysvětlí 3 ruční kroky (rozšíření do prohlížeče, první spuštění, klíč).
Žádná macOS oprávnění navíc (mikrofon apod.) nepotřebuje. Pokud na Macu chybí
novější Python, skript ho sám stáhne z python.org a jednou si řekne o heslo.
INTRO
echo
ask "Pokračovat? [Enter = ano, Ctrl+C = zrušit]"; read -r _

# --- 1. Python 3.9+ (když chybí, nainstalujeme ho sami) ---
# Skutečné minimum je 3.9: websockets>=14 (nová .request API) i pyobjc 11 jedou
# na 3.9 a zdroják nemá žádnou 3.10+ syntaxi. Záměrně NESPOUŠTÍME holý `python3`
# — to je Apple stub, který na čistém Macu vyvolá dialog "install developer tools".
# Hledáme jen reálné interprety.
MIN_MINOR=9
PY_INSTALL_VER=3.12.8   # co nainstalujeme, když žádný vhodný Python není

pick_python() {
  local cands=() c p ver
  for c in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3; do
    [ -x "$c" ] && cands+=("$c")
  done
  for c in /opt/homebrew/bin/python3.1* /usr/local/bin/python3.1*; do
    [ -x "$c" ] && cands+=("$c")
  done
  for p in python3.13 python3.12 python3.11 python3.10 python3.9; do
    c="$(command -v "$p" 2>/dev/null)" && cands+=("$c")
  done
  [ ${#cands[@]} -eq 0 ] && return 1
  for c in "${cands[@]}"; do
    ver="$("$c" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)" || continue
    [ "${ver%%.*}" = "3" ] && [ "${ver##*.}" -ge "$MIN_MINOR" ] && { echo "$c"; return 0; }
  done
  return 1
}

install_python() {
  local pkg="python-${PY_INSTALL_VER}-macos11.pkg"
  local url="https://www.python.org/ftp/python/${PY_INSTALL_VER}/${pkg}"
  local tmp="/tmp/$pkg"
  echo
  say "Nenašel jsem Python 3.${MIN_MINOR}+. Stáhnu a nainstaluju oficiální Python ${PY_INSTALL_VER} z python.org."
  echo "   • Stahuje se jen z python.org (HTTPS). Nic se nikam neodesílá."
  echo "   • macOS instalátor si řekne o tvé přihlašovací heslo (sudo) — to je v pořádku."
  ask "Nainstalovat Python? [Enter = ano, Ctrl+C = zrušit]"; read -r _
  say "Stahuji Python…"
  curl -fL --progress-bar -o "$tmp" "$url" || { err "Stažení Pythonu selhalo (zkontroluj internet)."; exit 1; }
  say "Instaluji Python — počkej, než to doběhne, okno nezavírej…"
  sudo installer -pkg "$tmp" -target /   # synchronní: pokračuje se až po dokončení
  rm -f "$tmp"
  ok "Python nainstalován"
}

if ! PY="$(pick_python)"; then
  install_python
  PY="$(pick_python)" || { err "Python se nepodařilo zprovoznit. Zavři a otevři Terminál a spusť skript znovu."; exit 1; }
fi
ok "python3: $("$PY" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')  ($PY)"

# --- 2. kam instalovat ---
DEST_DEFAULT="$HOME/Applications"
echo
say "Kam nainstalovat Menthol.app?"
echo "   1) $HOME/Applications   (jen pro tebe, bez hesla) [výchozí]"
echo "   2) /Applications        (pro všechny; může chtít heslo)"
ask "Volba [1/2, Enter = 1]:"; read -r choice
if [ "${choice:-1}" = "2" ]; then DEST="/Applications"; else DEST="$DEST_DEFAULT"; fi
mkdir -p "$DEST"
ok "Instaluji do: $DEST"

# --- 3. build prostředí + závislosti ---
echo
say "Teď vytvořím build venv a stáhnu Python knihovny (pár MB, chvíli to trvá)."
ask "Spustit? [Enter]"; read -r _
rm -rf "$BUILDVENV"
"$PY" -m venv "$BUILDVENV"
"$BUILDVENV/bin/pip" install --upgrade pip wheel >/dev/null
"$BUILDVENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" py2app
ok "Závislosti nainstalované"

# --- 4. ikona ---
if [ ! -f assets/menthol.icns ]; then
  say "Generuji ikonu appky"
  "$BUILDVENV/bin/python" assets/make_icon.py
  ICON=/tmp/menthol.iconset; rm -rf "$ICON"; mkdir -p "$ICON"
  for s in 16 32 128 256 512; do
    sips -z $s $s /tmp/menthol_icon.png --out "$ICON/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) /tmp/menthol_icon.png --out "$ICON/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICON" -o assets/menthol.icns
fi

# --- 5. build appky ---
say "Stavím Menthol.app (py2app)…"
rm -rf build dist
"$BUILDVENV/bin/python" setup.py py2app >/dev/null
[ -d dist/Menthol.app ] || { err "Build selhal."; exit 1; }
rm -rf "$DEST/Menthol.app"
cp -R dist/Menthol.app "$DEST/Menthol.app"

# --- 6. ad-hoc podpis (zdarma; nutné na Apple Silicon) ---
codesign --force --deep --sign - "$DEST/Menthol.app" >/dev/null 2>&1 && ok "Podepsáno (ad-hoc)" || err "Podpis selhal (appka možná i tak poběží)"
xattr -dr com.apple.quarantine "$DEST/Menthol.app" 2>/dev/null || true
echo
ok "Appka nainstalována: $DEST/Menthol.app"

# --- 7. ruční kroky s vysvětlením ---
cat <<STEPS

─── ZBÝVAJÍ 3 RUČNÍ KROKY (jednou) ───

1) ROZŠÍŘENÍ DO PROHLÍŽEČE  (proč: titulky čte rozšíření, ne appka)
   - Otevři Brave/Chrome v profilu, kde děláš schůzky.
   - Jdi na  brave://extensions  (nebo chrome://extensions ).
   - Zapni vpravo nahoře "Vývojářský režim".
   - "Načíst rozbalené" a vyber složku:
       $SCRIPT_DIR/browser-extension

2) PRVNÍ SPUŠTĚNÍ  (proč: appka není notarizovaná placeným certifikátem)
   - Finder → Aplikace → Menthol → pravým tlačítkem → Otevřít → Otevřít.
   - V horní liště přibude 🌿. (Žádné macOS oprávnění se nepovoluje.)

3) API KLÍČ  (proč: nápovědu generuje AI model pod tvým klíčem)
   - 🌿 → Nastavení → AI / nápověda → vyber Claude nebo Gemini a vlož klíč.
   - Nebo zvol "Nic neposílat" — pak jen ukládá přepis a nic neodesílá.

Pak: v Meetu zapni titulky (CC), 🌿 → Spustit poslech, a během hovoru
mačkej zkratku pro radu (výchozí Cmd+Shift+H).
STEPS
