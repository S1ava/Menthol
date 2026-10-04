// Menthol — sleduje živé titulky Google Meet a posílá finalizované věty
// (+ rozpracovaný "ocásek") na background service worker.
//
// Selektory ověřené živě 2026-08-20 a potvrzené v nezávislém open-source
// projektu (yunho0130/google-meet-cc-to-srt): .ygicle.VbkSUe = text titulku,
// .NWpY1d = jméno mluvčího, .nMcdL = jeden řádek titulku (jeden "tah" řeči).
// Google mění hashované třídy při redesignu UI — pokud přestane fungovat,
// zkontroluj konzoli (log níže) a přenastav tyhle konstanty.
(function () {
  const TEXT_SELECTOR = ".ygicle.VbkSUe";
  const SPEAKER_SELECTOR = ".NWpY1d";
  const ROW_SELECTOR = ".nMcdL";
  const DEBOUNCE_MS = 1200;

  const rowState = new WeakMap(); // row -> { timer, lastCaptured }
  let sawAnyCaption = false;

  function send(type, speaker, text) {
    text = (text || "").trim();
    if (!text) return;
    try {
      chrome.runtime.sendMessage({ type, speaker, text, ts: Date.now() }, () => {
        void chrome.runtime.lastError; // nikdo neposlouchá odpověď, jen ať netiskne warning
      });
    } catch (e) {
      console.warn("[Menthol] sendMessage selhal", e);
    }
  }

  function readRow(row) {
    const textEl = row.querySelector(TEXT_SELECTOR);
    if (!textEl) return null;
    const speakerEl = row.querySelector(SPEAKER_SELECTOR);
    return {
      speaker: speakerEl ? speakerEl.textContent.trim() : null,
      fullText: textEl.textContent.trim(),
    };
  }

  function delta(fullText, lastCaptured) {
    if (!lastCaptured) return fullText;
    if (fullText.startsWith(lastCaptured)) return fullText.slice(lastCaptured.length).trim();
    // Google občas u dlouhého monologu starý text v řádku zkrátí/nahradí —
    // v tom případě radši pošli celý aktuální text znovu, než něco ztratit.
    return fullText;
  }

  function captureStable(row) {
    const st = rowState.get(row);
    if (!st) return;
    const data = readRow(row);
    if (!data) return;
    if (data.fullText === st.lastCaptured) return;

    const d = delta(data.fullText, st.lastCaptured);
    if (d) send("final", data.speaker, d);
    st.lastCaptured = data.fullText;
  }

  function scheduleCapture(row) {
    if (!sawAnyCaption) {
      sawAnyCaption = true;
      console.log("[Menthol] První titulek zachycen, observer funguje");
    }
    let st = rowState.get(row);
    if (!st) {
      st = { timer: null, lastCaptured: "" };
      rowState.set(row, st);
    }
    clearTimeout(st.timer);
    st.timer = setTimeout(() => captureStable(row), DEBOUNCE_MS);

    const data = readRow(row);
    if (data) {
      const tail = delta(data.fullText, st.lastCaptured);
      if (tail) send("interim", data.speaker, tail);
    }
  }

  function flushRow(row) {
    const st = rowState.get(row);
    if (st) clearTimeout(st.timer);
    captureStable(row);
    rowState.delete(row);
  }

  const observer = new MutationObserver((mutations) => {
    const touchedRows = new Set();
    const removedRows = new Set();

    for (const m of mutations) {
      const target = m.target.nodeType === 3 ? m.target.parentElement : m.target;
      const row = target ? target.closest(ROW_SELECTOR) : null;
      if (row) touchedRows.add(row);

      if (m.removedNodes && m.removedNodes.length) {
        m.removedNodes.forEach((n) => {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches(ROW_SELECTOR)) removedRows.add(n);
          if (n.querySelectorAll) n.querySelectorAll(ROW_SELECTOR).forEach((r) => removedRows.add(r));
        });
      }
    }

    touchedRows.forEach(scheduleCapture);
    removedRows.forEach(flushRow);
  });

  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  console.log("[Menthol] Caption observer spuštěn — čeká na titulky (musí být zapnuté CC)");

  // --- Skrytí titulků na obrazovce ---
  // Titulky musí být v Meetu zapnuté (CC), ale nemusí rušit: tímhle je vizuálně
  // schováme (opacity:0), v DOMu dál běží, takže je Menthol pořád čte.
  // Výchozí = skryté. Přepnutí: Alt+Shift+C (v Meet tabu). Stav v localStorage.
  function applyHideCC(hide) {
    let st = document.getElementById("menthol-hide-cc");
    if (!st) {
      st = document.createElement("style");
      st.id = "menthol-hide-cc";
      (document.head || document.documentElement).appendChild(st);
    }
    st.textContent = hide
      ? ROW_SELECTOR + "{opacity:0 !important;pointer-events:none !important;}"
      : "";
  }
  let hideCC = true;
  try { hideCC = localStorage.getItem("menthol_hide_cc") !== "0"; } catch (e) { /* noop */ }
  applyHideCC(hideCC);
  console.log("[Menthol] Titulky na obrazovce:", hideCC ? "SKRYTÉ" : "viditelné");
  function toggleCC() {
    hideCC = !hideCC;
    try { localStorage.setItem("menthol_hide_cc", hideCC ? "1" : "0"); } catch (e) { /* noop */ }
    applyHideCC(hideCC);
    console.log("[Menthol] Titulky na obrazovce:", hideCC ? "SKRYTÉ" : "viditelné");
  }

  // Příkazy z appky (přes background): globální zkratka na titulky + chat-notice.
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || !msg.cmd) return;
    if (msg.cmd === "toggle_cc") toggleCC();
    else if (msg.cmd === "chat_notice") postChatMessage(msg.text || "");
  });

  // Napíše zprávu do chatu Meetu (transparentní oznámení o přepisu).
  // Meet UI je křehké (hashované třídy), tak hledáme přes aria-label/ikony.
  function postChatMessage(text) {
    if (!text) return;
    function setNativeValue(el, value) {
      const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value");
      if (d && d.set) d.set.call(el, value); else el.value = value;
    }
    function findChatInput() {
      return document.querySelector(
        'textarea[aria-label*="essage" i], textarea[aria-label*="práv" i], textarea[placeholder]'
      );
    }
    function openChat() {
      const btn = [...document.querySelectorAll("button[aria-label]")].find((b) =>
        /chat|zpráv/i.test(b.getAttribute("aria-label") || "")
      );
      if (btn) btn.click();
    }
    if (!findChatInput()) openChat();
    let tries = 0;
    const timer = setInterval(() => {
      tries++;
      const inp = findChatInput();
      if (inp) {
        clearInterval(timer);
        inp.focus();
        setNativeValue(inp, text);
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        inp.dispatchEvent(new KeyboardEvent("keydown", {
          key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true,
        }));
        const send = [...document.querySelectorAll("button[aria-label]")].find((b) =>
          /send|odeslat/i.test(b.getAttribute("aria-label") || "")
        );
        if (send) send.click();
        console.log("[Menthol] chat-notice odeslán");
      } else if (tries > 20) {
        clearInterval(timer);
        console.warn("[Menthol] chat input nenalezen — notice neodeslán");
      }
    }, 300);
  }

  // Heartbeat + metadata: každých 5 s (jen když jsme v konkrétním meetingu)
  // pošle titulek + kód meetingu. Server z toho pojmenuje soubor a zároveň to
  // slouží jako "žiju" signál — když heartbeat přestane (zavřený tab, položený
  // hovor, odchod z meetingu), appka po chvíli sama zastaví poslech.
  // Kód meetingu z URL: cokoli jako /abc-defg-hij (písmena/číslice/pomlčky,
  // aspoň 8 znaků). Landing "/" nebo "/new" se nepočítá.
  const MEETING_RE = /^\/[a-z0-9-]{8,}$/i;
  function meetingCode() {
    const p = location.pathname || "";
    return MEETING_RE.test(p) ? p.slice(1) : "";
  }

  // Jméno schůzky z obrazovky: Meet ho ukazuje vlevo dole (u kalendářové
  // schůzky = název události, u instantní = jméno hostitele). Nemá stabilní
  // selektor, tak ho hledáme heuristicky: nejspodnější-nejlevější krátký
  // textový span. Vrací "" když nic rozumného nenajde.
  function meetingName() {
    const cands = [];
    document.querySelectorAll("span.notranslate").forEach((s) => {
      if (s.children.length) return;
      const t = (s.textContent || "").trim();
      if (t.length < 2 || t.length > 80) return;
      const r = s.getBoundingClientRect();
      if (r.width > 0 && r.y > window.innerHeight * 0.6 && r.x >= 0 && r.x < 440) {
        cands.push({ t, y: r.y, x: r.x });
      }
    });
    cands.sort((a, b) => b.y - a.y || a.x - b.x);
    return cands.length ? cands[0].t : "";
  }
  // Jsme v AKTIVNÍM hovoru? Poznáme podle tlačítka "zavěsit" (ikona call_end).
  // Ligatura "call_end" je jazykově nezávislá (na rozdíl od aria-label).
  function inCall() {
    const syms = document.querySelectorAll(
      ".google-symbols, .material-symbols-outlined, [class*='symbols']"
    );
    for (const s of syms) {
      if ((s.textContent || "").trim() === "call_end") return true;
    }
    return false;
  }

  let _lastSkip = "";
  let _sawCallEnd = false; // viděli jsme tlačítko zavěsit = byli jsme v hovoru
  function sendMeta() {
    const code = meetingCode();
    if (!code) {
      if (location.pathname !== _lastSkip) {
        _lastSkip = location.pathname;
        console.log("[Menthol] meta SKIP — pathname:", location.pathname);
      }
      return; // nejsme ve schůzce → žádný heartbeat
    }
    _lastSkip = "";
    const now = inCall();
    if (now) _sawCallEnd = true;
    // Byli jsme v hovoru a tlačítko zavěsit zmizelo → hovor ukončen. Přestaň
    // posílat heartbeat → appka se sama zastaví. (Když detekce nikdy nechytla,
    // _sawCallEnd zůstane false a jedeme jako dřív podle URL — bez planých stopů.)
    if (_sawCallEnd && !now) {
      console.log("[Menthol] hovor ukončen (call_end zmizel) → stop heartbeat");
      return;
    }
    // document.title je nejspolehlivější: u pojmenované schůzky "Meet – <název>"
    // (appka si "Meet – " odřízne), u nepojmenované "Meet – <kód>" → fallback na
    // kód. Screen-scrape (meetingName) chytal špatně vlastní dlaždici, proto pryč.
    const name = document.title;
    console.log("[Menthol] meta SEND — code:", code, "name:", name);
    try {
      chrome.runtime.sendMessage(
        { type: "meta", title: name, code: code, ts: Date.now() },
        () => { void chrome.runtime.lastError; }
      );
    } catch (e) {
      console.warn("[Menthol] meta sendMessage selhal", e);
    }
  }
  setTimeout(sendMeta, 2000);
  setInterval(sendMeta, 5000);
})();
