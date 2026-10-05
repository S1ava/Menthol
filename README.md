# 🌿 Menthol

Realtime našeptávač do hovoru pro macOS. Čte živé titulky Google Meetu a na
stisk klávesové zkratky ti uprostřed obrazovky ukáže, na co se zeptat nebo co
říct. Overlay vidíš jen ty, ve sdílení obrazovky se nezobrazuje.

Běží jako appka v horní liště. Přepis bere z titulků Meetu, takže nepotřebuje
mikrofon, žádný audio driver ani žádné macOS oprávnění navíc.

> **Transparentnost:** Ve free verzi Menthol při začátku přepisu automaticky
> napíše do chatu schůzky krátkou zprávu, že probíhá přepis (s odkazem, kde si
> Menthol stáhnout). Účastníci tak vždy vědí, že se přepisuje.

---

## Co potřebuješ (jednou)

1. **Mac** s macOS 12 nebo novějším.
2. **Brave** nebo **Google Chrome** (titulky čte rozšíření, které běží jen v
   těchto prohlížečích — Safari ani samostatná „Meet.app" nefungují).
3. **Python 3** (na Macu často už je; jinak `brew install python` nebo
   z <https://www.python.org/downloads/>).
4. **API klíč** pro AI nápovědu — Anthropic (Claude) nebo Google (Gemini).
   Anthropic: <https://console.anthropic.com> → API Keys.
   **Nebo vůbec žádný** — v Nastavení lze zvolit „Nic neposílat": Menthol pak
   jen ukládá přepis a nic nikam neodesílá (bez nápovědy).

---

## Instalace krok za krokem

### 1. Stáhni projekt
```bash
git clone https://github.com/S1ava/Menthol.git
cd Menthol
```
Nebo ZIP: **Code → Download ZIP**, rozbal, a v Terminálu se do složky přesuň.

### 2. Spusť instalaci
```bash
./install.sh
```
Script se tě na vše zeptá a vysvětlí, proč to chce. Postaví appku do
`~/Applications/Menthol.app` (nebo `/Applications`). Nepotřebuje sudo.

### 3. Načti rozšíření do prohlížeče (čte titulky)
1. V Brave/Chrome otevři `brave://extensions` (resp. `chrome://extensions`).
2. **Pro profil, ve kterém děláš schůzky** (pozor: rozšíření jsou per-profil).
3. Vpravo nahoře zapni **Vývojářský režim / Developer mode**.
4. **Načíst rozbalené / Load unpacked** → vyber složku **`browser-extension`**.

### 4. Spusť Menthol a nastav AI
1. Finder → **Aplikace** → **Menthol**. Poprvé klikni **pravým → Otevřít →
   Otevřít** (appka není notarizovaná, proto to jednou odklikneš).
2. V horní liště přibude **🌿**. Klikni → **Nastavení → AI / nápověda**: vyber Claude
   nebo Gemini a vlož klíč (uloží se do chráněného souboru, ne do repa). Nebo
   zvol **Nic neposílat**.
3. V **Nastavení → Prohlížeč pro Meet** zvol Brave nebo Chrome (ten, kam jsi
   načetl rozšíření).

### Oprávnění
Menthol **nepotřebuje** Sledování vstupu ani mikrofon. Jediné, co macOS jednou
řeší, je Gatekeeper (to „Otevřít" pravým tlačítkem v kroku 4).

---

## Používání

1. V horní liště **🌿 → Spustit poslech** (ikona se změní na → 🌿▶).
2. Měl by se otevřít prohlížeč rovnou na stránce Google meet. Pokud se tak nestalo, Google Meet otevři v **normálním okně** Brave/Chrome a zapni **titulky (CC)**.
4. **Zkratky:**
   - **Získat radu** (výchozí `cmd+shift+h`) — ukáže nápovědu uprostřed obrazovky.
   - **Překrýt titulky** (výchozí `cmd+shift+j`) — schová/zobrazí titulky na obrazovce (běží dál pro
     Menthol, jen tě neruší).
   Obě zkratky změníš v **Nastavení → Zkratky**.
5. Po ukončení hovoru se poslech **sám zastaví** za 15 sekund (když zavěsíš / zavřeš tab), nebo ručně
   **🌿 → Zastavit poslech**.

Přepis se ukládá jako `meet_<datum_čas>_<název_schůzky>.txt` do
`~/Documents/Menthol-recordings/` (složku změníš v Nastavení → Přepisy).

---

## Když to nepřepisuje
1. **Titulky (CC) nejsou zapnuté** v Meetu.
2. **Meet běží v jiném profilu**, než kam jsi načetl Chrome/Brave rozšíření (rozšíření jsou
   per-profil), nebo v tabu otevřeném dřív než rozšíření → dej **Cmd+R**.
3. **Safari / samostatná Meet.app** — tam rozšíření neběží, použij normální okno
   Brave/Chrome.
4. **Po aktualizaci rozšíření** restartuj prohlížeč (ne jen „Reload") — MV3
   service worker jinak může běžet ve staré verzi.
5. Log: `~/Library/Logs/Menthol/menthol.log`.

---

## Odinstalace
- Smaž `Menthol.app` z Aplikací.
- Nastavení a klíče: `~/Library/Application Support/Menthol/`.
- Přepisy: `~/Documents/Menthol-recordings/`.
- Rozšíření odeber na `brave://extensions`.

---

## Soukromí
- API klíče jsou v chráněném souboru jen pro tvůj účet, nikdy ne v repu.
- V režimu Claude/Gemini se text přepisu posílá do zvolené LLM služby pod tvým
  klíčem. V režimu **„Nic neposílat"** neodchází nikam nic.

## Licence
Zdrojově dostupné, **ne open-source**. Viz [LICENSE](LICENSE). Kopírování,
úpravy a šíření bez souhlasu autora nejsou povoleny.

---

Vyvinul **[Advantiq](https://advantiq.cz)** — externí projektové řízení a vývoj
řešení na míru. Když ti Menthol šetří čas, můžeš podpořit vývoj na
[GitHub Sponsors](https://github.com/sponsors/S1ava). ☕

🌿 **[advantiq.cz](https://advantiq.cz)**
