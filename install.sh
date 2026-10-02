#!/bin/bash
# =====================================================================
#  Menthol — lokální instalace do Mac appky (captions build, py2app)
#  Postaví samostatný Menthol.app (vlastní identita, jen v horní liště),
#  bez placeného Apple certifikátu, bez Whisper/BlackHole.
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
BUILDVENV="$SCRIPT_DIR/build-venv"

say() { printf "\033[96m▶ %s\033[0m\n" "$1"; }
ok()  { printf "\033[92m✓ %s\033[0m\n" "$1"; }
err() { printf "\033[91m✗ %s\033[0m\n" "$1" >&2; }

# --- 1. kontrola Pythonu ---
if ! command -v python3 >/dev/null 2>&1; then
  err "Nenašel jsem python3. Nainstaluj z https://www.python.org/downloads/ nebo 'brew install python'."
  exit 1
fi
ok "python3 nalezen ($(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'))"

# --- 2. build prostředí (izolované, jen pro sestavení) ---
say "Připravuji build prostředí (venv)"
rm -rf "$BUILDVENV"
python3 -m venv "$BUILDVENV"
"$BUILDVENV/bin/pip" install --upgrade pip wheel >/dev/null
say "Instaluji závislosti + py2app (může chvíli trvat)"
"$BUILDVENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" py2app
ok "Závislosti nainstalované"

# --- ikona appky (.icns) — vygeneruj, pokud v repu chybí ---
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

# --- 3. build appky přes py2app ---
say "Stavím Menthol.app (py2app)"
rm -rf build dist
"$BUILDVENV/bin/python" setup.py py2app >/dev/null
[ -d dist/Menthol.app ] || { err "Build selhal — dist/Menthol.app nevzniklo."; exit 1; }
ok "Appka postavena"

# --- 4. instalace do Aplikací ---
DEST="/Applications"
if [ ! -w "$DEST" ]; then
  DEST="$HOME/Applications"
  mkdir -p "$DEST"
  say "Do /Applications nemám právo zápisu, instaluji do $DEST"
fi
rm -rf "$DEST/Menthol.app"
cp -R dist/Menthol.app "$DEST/Menthol.app"

# --- 5. ad-hoc podpis (zdarma; nutné na Apple Silicon) ---
say "Ad-hoc podpis"
codesign --force --deep --sign - "$DEST/Menthol.app" >/dev/null 2>&1 && ok "Podepsáno" || err "Podpis selhal (appka možná i tak poběží)"

# odstranit quarantine, kdyby nějaká byla (lokální build ji nemá, ale pro jistotu)
xattr -dr com.apple.quarantine "$DEST/Menthol.app" 2>/dev/null || true

echo
ok "Hotovo. Appka: $DEST/Menthol.app"
echo
printf "\033[93m─── DALŠÍ KROKY (jednou) ───\033[0m\n"
cat <<STEPS
1) Načti browser extension (Brave nebo Chrome):
   - otevři  brave://extensions  (nebo  chrome://extensions )
   - vpravo nahoře zapni "Vývojářský režim / Developer mode"
   - klikni "Načíst rozbalené / Load unpacked" a vyber složku:
     $SCRIPT_DIR/browser-extension

2) Spusť Menthol:
   - Finder → Aplikace → Menthol  (poprvé pravým → Otevřít → Otevřít)
   - v horní liště naskočí 🌿 (appka NENÍ v Docku, je jen v liště)

3) V liště 🌿 → "Nastavit Anthropic klíč…" a vlož svůj klíč
   (https://console.anthropic.com → API Keys)

Zkratku (výchozí Cmd+Shift+H) můžeš změnit v 🌿 → "Zkratka: … (změnit…)".
Žádné systémové oprávnění není potřeba.

Pak: v Meetu zapni titulky (CC), 🌿 → "Spustit poslech",
a během hovoru mačkej zkratku pro nápovědu.
STEPS
