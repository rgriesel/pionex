# Pionex integration evidence

Official documentation checked 2026-09-28. Refresh at integration and before enabling new capabilities. Documentation does not prove account access.

| Area | Official source | Integration consequence |
|---|---|---|
| Signing | [Authentication](https://www.pionex.com/docs/api-docs/trade-api/general-info/authentication) | Private calls use timestamped HMAC SHA256 and PIONEX headers, with separate read/trade permissions. Test against current examples; signed and sent body bytes must match. |
| Symbol rules | [Common](https://www.pionex.com/docs/api-docs/trade-api/common) | `GET /api/v1/common/symbols` exposes enabled state, precisions, spot `minAmount`, and quantity constraints. Never assume one universal minimum. |
| Orders | [Trade](https://www.pionex.com/docs/api-docs/trade-api/trade) | Creation lists LIMIT/MARKET. Limits use price/size; market buys use quote amount; market sells use base size. Client-ID lookup, fills, open orders, and cancellation support recovery. This does not establish STOP/OCO/post-only support. |
| Balances | [Account](https://www.pionex.com/docs/api-docs/trade-api/account) | `GET /api/v1/account/balances` excludes bot/earn accounts. Include separate bot inventory explicitly if used. |
| Data | [Market](https://www.pionex.com/docs/api-docs/trade-api/market) | Inspect actual history, depth, interval, and paging semantics before implementing collection. |
| Limits | [Rate limits](https://www.pionex.com/docs/api-docs/trade-api/general-info/rate-limits) | Weighted IP/account limits are independent; documentation describes 10/second and 429 bans. Start with a conservative shared budget of 5 weight/second and reserve exit/recovery capacity. |
| Costs | [Fees](https://www.pionex.com/en/fees) | Standard spot maker/taker shown as 0.050% per side: research assumption 0.10% round trip plus spread/impact. Verify actual pair/account fees. |
| Grid protection | [Spot Grid API](https://www.pionex.com/docs/api-docs/bot-api/spot-grid) | Documents stop/target settings, delays, inventory, and closing behavior. Verify access, zero-delay intent, minimum investment, and actual liquidation. Grid profit is not total P&L; enum names alone do not prove the closing behavior. |
| Security | [Overview](https://www.pionex.com/docs/api-docs) | Recommends IP restrictions and keeping API credentials private. |
| Institutional access | [Institution API](https://www.pionex.com/docs/api-docs/institution-api/general-info/basic-info) | Described as internal for onboarded institutional providers. Never assume retail access to internal APIs. |

Use only endpoints verified for this account. Do not assume all REST/WebSocket products share signing rules or budgets. Check third-party SDK methods against current specifications and dependencies before adoption.

This skill has not verified a public spot sandbox. Use an internal paper simulator if no suitable sandbox exists. A futures demo is not a spot API sandbox. Clearly label simulated fills.

Create a capability report containing retrieval times/URLs, observed account permissions/scope, pair rules/status, fee source, request/stream limits, order-ID semantics, stop behavior, bot balance scope, and unsupported/untested items. Keep redacted fixtures and refresh changing rules routinely.
