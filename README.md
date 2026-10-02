# 🌿 Menthol

Realtime našeptávač do hovoru. Čte živé titulky Google Meetu a na stisk
**Cmd+Shift+H** ti uprostřed obrazovky ukáže, na co se zeptat nebo co říct.
Overlay vidíš jen ty, ve sdílení obrazovky se nezobrazuje.

Běží jako appka v horní liště macOS. Přepis bere z titulků Meetu, takže
nepotřebuje mikrofon, žádný audio driver ani placené přepisové služby.

---

## Co potřebuješ (jednou)

1. **Mac** s macOS 12 nebo novějším.
2. **Brave** nebo **Google Chrome**.
3. **Python 3** (na Macu často už je). Když není, nainstaluj z
   <https://www.python.org/downloads/> nebo `brew install python`.
4. **Anthropic API klíč** (placené API Claude). Získáš na
   <https://console.anthropic.com> → *API Keys*. Gemini klíč je volitelný.

---

## Instalace krok za krokem

### 1. Stáhni projekt
Buď přes Git:
```bash
git clone <adresa-repozitáře> menthol
cd menthol
```
nebo si stáhni ZIP z GitHubu (tlačítko **Code → Download ZIP**), rozbal, a v
Terminálu se do složky přesuň (`cd` a přetáhni složku do okna Terminálu).

### 2. Spusť instalaci
```bash
./install.sh
```
Script postaví appku do `~/Applications/Menthol.app` (bez hesla, bez sudo).
Chvíli to trvá, stahují se knihovny. Až doběhne, vypíše další kroky.

### 3. Načti browser extension (ta čte titulky)
1. V prohlížeči otevři `brave://extensions` (nebo `chrome://extensions`).
2. Vpravo nahoře zapni **Vývojářský režim / Developer mode**.
3. Klikni **Načíst rozbalené / Load unpacked** a vyber složku
   **`browser-extension`** uvnitř staženého projektu.
4. Nechej ji zapnutou.

> ⚠️ **Důležité:** Meet musí běžet v **normálním okně** prohlížeče. Samostatná
> „appka" (PWA zkratka) titulky nepředá.

### 4. Spusť Menthol a nastav klíč
1. Finder → **Aplikace** (nebo `~/Applications`, pokud instalace neměla práva do
   systémových Aplikací) → **Menthol**. Kdyby macOS hlásil neznámého vývojáře:
   klikni na appku **pravým tlačítkem → Otevřít → Otevřít**. (Appka není
   notarizovaná, proto to jednou odklikneš.)
2. Menthol běží **jen v horní liště**, ne v Docku. Objeví se **🌿**. Klikni na něj
   → **Nastavit Anthropic klíč…** a vlož svůj klíč. Uloží se do chráněného
   souboru (`secrets.json`, práva jen pro tvůj účet), ne do repozitáře.

### 5. (Volitelně) změň klávesovou zkratku
Výchozí je **Cmd+Shift+H**. Změníš ji v **🌿 → Zkratka: … (změnit…)**.
Žádné systémové oprávnění není potřeba (hotkey je nativní macOS registrace).
Vyhni se běžným zkratkám jako Cmd+C/X/V — Menthol je „spotřebuje".

---

## Používání

1. Otevři Google Meet v normálním okně prohlížeče a **zapni titulky (CC)**.
2. V liště klikni na **🌿 → Spustit poslech**. Ikona se změní na **🌿▶**.
3. Během hovoru mačkej **Cmd+Shift+H** — nápověda se ukáže uprostřed obrazovky.
4. **Role rádce** (obchodník / kouč / produkťák) přepneš v menu 🌿.
5. Po hovoru **🌿 → Zastavit poslech**.

Menthol umí i sám upozornit, když se v hovoru děje něco, na co reagovat
(overlay se zprávou). Zapíná se v configu (`alerts`).

---

## Když to nepřepisuje

Nejčastější příčiny, v tomhle pořadí:
1. **Titulky (CC) nejsou v Meetu zapnuté.** Menthol jen čte titulky z obrazovky.
2. **Meet běží v PWA „app" okně**, ne v normálním okně prohlížeče. Otevři ho
   přes 🌿 → *Otevřít Google Meet*, nebo běžnou záložku.
3. **Extension není načtená / je vypnutá.** Zkontroluj `brave://extensions`.
4. Log appky je v `~/Library/Logs/Menthol/menthol.log` — pošli ho, když nic
   z výše uvedeného nepomůže.

---

## Odinstalace
- Smaž `~/Applications/Menthol.app`.
- Volitelně nastavení a klíče: `~/Library/Application Support/Menthol/`
  (`config.json`, `secrets.json`), log `~/Library/Logs/Menthol/` a přepisy
  `~/Documents/Menthol-recordings/`.
- Extension odeber na `brave://extensions`.

---

## Poznámky
- Klíče leží v `~/Library/Application Support/Menthol/secrets.json` (práva 0600,
  jen tvůj účet), nikdy ne v repozitáři ani v bundlu appky.
- Appka není podepsaná placeným Apple certifikátem. Po **updatu** může macOS
  chtít znovu povolit *Sledování vstupu* — to je daň za bezplatnou distribuci.
- Přepis každého hovoru se ukládá jako `meet_<datum_čas>_<název_meetingu>.txt`
  do `~/Documents/Menthol-recordings/` (výchozí). Složku změníš v
  **🌿 → Změnit složku přepisů…**, otevřeš v **🌿 → Otevřít složku přepisů**.
  Ukládání jde vypnout v configu (`recording.save_transcript`).
