// Menthol — udržuje WebSocket spojení na lokální Python server a přeposílá
// zprávy od content scriptu. Service worker v MV3 může kdykoli usnout, proto
// se spojení znovu naváže při každé probuzené události (alarm i onMessage).

const WS_URL = "ws://localhost:8765";
const RECONNECT_DELAY_MS = 2000;
const QUEUE_LIMIT = 200;

let ws = null;
let reconnectTimer = null;
const queue = [];

function flushQueue() {
  while (queue.length && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(queue.shift());
  }
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      console.log("[Menthol] WS připojen");
      clearTimeout(reconnectTimer);
      flushQueue();
    };
    ws.onclose = () => {
      ws = null;
      scheduleReconnect();
    };
    ws.onerror = () => {
      try { ws && ws.close(); } catch (e) { /* noop */ }
    };
  } catch (e) {
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const payload = JSON.stringify(msg);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(payload);
  } else {
    if (queue.length >= QUEUE_LIMIT) queue.shift();
    queue.push(payload);
    connect();
  }
  sendResponse({ ok: true });
  return false;
});

// Keepalive: MV3 service worker po ~30s nečinnosti usne a vezme si s sebou
// otevřený socket. Pravidelný alarm ho probudí a spojení obnoví.
chrome.alarms.create("menthol-keepalive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener(() => connect());

connect();
