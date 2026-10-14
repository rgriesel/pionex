# Pionex WebSocket streams (public only for this repo)

Official: https://pionex-doc.gitbook.io/apidocs/websocket/general-info.md (and `/websocket/public-stream/trade.md`, `/depth.md`). Verified live on 2026-10-14.

| Stream | URL | Auth |
|---|---|---|
| Public | `wss://ws.pionex.com/wsPub` | none |
| Private | `wss://ws.pionex.com/ws` | API key + signature. DO NOT USE in this repo |

The private topics `ORDER`, `FILL`, `BALANCE` need keys; skip them.

## Protocol

Send JSON text frames:

```json
{"op": "SUBSCRIBE", "topic": "TRADE", "symbol": "BTC_USDT"}
{"op": "SUBSCRIBE", "topic": "DEPTH", "symbol": "BTC_USDT", "limit": 5}
{"op": "UNSUBSCRIBE", "topic": "TRADE", "symbol": "BTC_USDT"}
```

Acks (observed): `{"type":"SUBSCRIBED","topic":"TRADE","symbol":"BTC_USDT"}`. Server errors carry `code` and `message` (`INVALID_OP`, `INVALID_TOPIC`, `INVALID_SYMBOL`, `PARAMETER_ERROR`, `SUBSCRIBED_TOPICS_EXCEED_LIMIT`).

Server frames are BINARY frames containing UTF-8 JSON (verified): decode bytes to text before `json.loads`.

DEPTH push (observed): a full top-N snapshot every ~0.6 s (30 pushes in ~20 s), not an incremental diff. `limit` is 1 to 100; the docs do not state the default, so always send it.

```json
{"topic":"DEPTH","symbol":"BTC_USDT","data":{"bids":[["81708.77","7.590031"]],"asks":[["81708.78","12.960507"]]},"timestamp":1792010855765}
```

TRADE push (observed): batches of recent trades (up to 100 per message per the docs), usually 1 to 3 rows:

```json
{"topic":"TRADE","symbol":"BTC_USDT","data":[{"symbol":"BTC_USDT","tradeId":"320000000879814402","price":"81708.54","size":"0.000015","side":"SELL","timestamp":1792010856682}],"timestamp":1792010856769}
```

`side` is the taker's direction. Trade ids are strictly increasing per symbol, so use them to de-duplicate after reconnects.

Heartbeat: the server sends `{"op":"PING","timestamp":...}` roughly every 15 s (first one arrived at ~16 s). Reply `{"op":"PONG","timestamp":<now ms>}`. After 3 unanswered PINGs the server sends `{"op":"CLOSE"}` and drops the connection. Reconnect with backoff and re-subscribe; there is no replay of missed messages.

Limits: 10 connections per IP. Use one connection and many topics.

## Minimal Node.js check (Node 22+, global `WebSocket`; no dependencies, no keys)

```js
const ws = new WebSocket("wss://ws.pionex.com/wsPub");
ws.binaryType = "arraybuffer";
ws.onopen = () => ws.send(JSON.stringify({ op: "SUBSCRIBE", topic: "DEPTH", symbol: "BTC_USDT", limit: 5 }));
ws.onmessage = (ev) => {
  const m = JSON.parse(typeof ev.data === "string" ? ev.data : new TextDecoder().decode(ev.data));
  if (m.op === "PING") return ws.send(JSON.stringify({ op: "PONG", timestamp: Date.now() }));
  console.log(JSON.stringify(m).slice(0, 300));
};
setTimeout(() => ws.close(), 10000);
```

## Python

The standard library has no WebSocket client, and the lab's data layer is stdlib-only, so the lab does NOT use the WebSocket today: the collector polls REST at 1 s (book) and 3 s (depth). (`pionex_lab/data/live_depth.py` and `depth.py` are Binance proxy-venue depth recorders, not Pionex streams; `cli.py capability` records "websocket: not used; REST polling only".) If a stream is needed, run a small separate collector process (Node as above, or a vetted `websockets` package) that writes to its own database, and keep it public-only. Do not add third-party dependencies to the engine without the lead's approval.
