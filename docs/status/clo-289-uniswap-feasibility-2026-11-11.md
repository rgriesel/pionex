# CLO-289 ? free Uniswap V3 range-book feasibility

2026-11-11. **NO: complete free reconstruction is not demonstrated by this pilot.**
This is a data-access result, not proof that no free implementation can work. No returns,
capacities, activations, backtest or strategy trial were calculated/registered. Ethereum
Uniswap data is non-Pionex venue data; it is not a substitute for Pionex execution evidence.

The card is `research/ideas/2026-11-11.md`. Coverage check found no existing Uniswap range-book
implementation or matching completed strategy-log evaluation. Existing CLO-272 RPC probe was
reviewed; existing CTA/factor/bootstrap frameworks do not implement tick-book ingestion and
were not run because this assignment excludes strategy testing. OpenAI quota: 5h 8%, week 53%.

## Measured evidence

| Check | Observed result | Remaining gap |
|---|---|---|
| Correct pool | dRPC chainId=1; official factory getPool(WETH,USDC,500) returns 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640; token0 USDC/6 decimals, token1 WETH/18, fee500, spacing10 | Identity verified at E only |
| Historical state | dRPC slot0 at block20,000,000 succeeds; PublicNode returns403 `Archive requests require a personal token` | Full archive range/depth not established |
| Historical logs | dRPC returns109 pool logs for20,000,000..20,000,099 | Unfiltered endpoint probe only; not a complete ordered daily Mint/Burn stream |
| Other free endpoints | 1rpc state unavailable at20M, logs50-block limit; Ankr requires key; Llama525; Cloudflare state/log errors; Merkle429 | No alternate complete source demonstrated |
| Complete bitmap | 694 words required over full legal tick domain at spacing10; 484 successful words, six429 responses; remaining work not completed | Cannot infer missing words or ticks as zero |
| Throughput | Eight workers;516 pilot requests in45.812s, then dRPC429/code15 `You reached Public endpoint rate limit, please upgrade to paid plan` | Burst rate is not sustained throughput; no ten-minute completion claim |
| Reconciliation | NOT REACHED; no full S snapshot, tick reads, replay or complete E comparison | Exact whole-curve equality and pool active-liquidity identity required |
| Unit tests | Synthetic Mint/Burn churn, zero Burn, negative tick decoding, malformed ABI, missing initial liquidity covered | Tests establish code behavior, not missing market-data completeness |

The initial default-Python-agent requests returned403/1010 for several providers. The standard
Mozilla user-agent used by the existing collector restored access to PublicNode/dRPC/1rpc;
those initial transport failures are retained but are not called archive denials.

Fixed pilot E=20007200; binary-searched S=20000038, the latest block at/before E.timestamp minus86400.
S/S+1/E headers and hashes are retained in the JSON. Requests record UTC send/receipt times.
Historical hashes were captured, but post-read hash checks were not reached after throttling.
The script would exhaust all bitmap words, read gross/net liquidity at every initialized tick,
replay all Mint/Burn events sorted by block/transaction/log index, reject removed/duplicate events,
and compare every gross/net tick and active liquidity with independently read E state.

A complete tick gross/net curve is enough for capacity integrals: cumulative liquidityNet gives
all active intervals. It does **not** uniquely identify original provider/range pairs. A literal
outstanding range manifest needs an initial owner/range ledger or complete genesis-to-S event
history; that was not obtained. Even matching active liquidity alone would not prove far-tick
or event completeness. The pilot therefore supplies neither a complete range manifest nor a
reconciled equivalent interval curve.

## Why / what would change it / next

**WHY:** incomplete initial state after a measured free-provider rate limit; later archive-depth,
ordered daily logs, full state reconciliation and deadline gates remain unmeasured.
**WHAT:** demonstrate complete state and logs using no-key free reads with reliable bounded
request volume, exact gross/net replay equality and independent active-liquidity reconciliation.
**NEXT:** propose one separate *data feasibility* pilot using eight sequential100-word read-only
multicall chunks per snapshot, one worker and at most one outer request/s, checkpoint/restart,
three fixed archive dates and one full historical day. Availability/contract/gas caps must first
be verified. This is a proposed unrun infrastructure method, not a changed strategy or a trial.
The explicit assignment prohibits registering a strategy trial; none was registered. The CEO
can assign this follow-up before deciding whether a trading test merits pre-registration.

No important/critical Telegram trigger: routine negative feasibility finding, no trading action.

## Provenance and sources

The source was written at03:49:38 SAST and the reconstruction began at03:49:38.830 SAST.
Its original docstring mistakenly said03:55 SAST. That timestamp was corrected after the run;
the original remains verbatim in the report. No claim of a correctly timestamped pre-registration
is made, and no strategy trial was run. Parameters and gates were unchanged; no rerun.

- [Official Uniswap full-tick retrieval](https://developers.uniswap.org/docs/sdks/v3/guides/pool-data): bitmap enumeration followed by initialized tick reads.
- [Official pool state interface](https://raw.githubusercontent.com/Uniswap/v3-core/main/contracts/interfaces/pool/IUniswapV3PoolState.sol): liquidity() concerns only current in-range liquidity.
- [Official pool events](https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolEvents.sol): Mint/Burn event definitions.
- [PublicNode](https://ethereum.publicnode.com/): public endpoint; actual archive denial measured separately.

Raw outputs in the primary workspace: `var/reports/uniswap_feasibility_clo289.json`,
`.json.rpc.json`, `clo289_endpoint_probe.json`, `clo289_endpoint_probe_ua.json`;
`clo289_summary.json` contains their SHA256s and disposition. Failed reconstruction output is
retained; missing evidence is never relabelled a PASS. Source: `research/uniswap_feasibility_clo289.py`.

Validation: main suite606 tests, one skipped, one error in documented Windows
`test_read_only_uri_encodes_awkward_paths` (WinError123 creating a `?` filename);
legacy suite12/12 pass; five new unit tests pass, including transport-failure persistence.
