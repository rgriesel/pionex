"""Build dashboard/index.html from the skill's dashboard template.

The template (.claude/skills/pionex-trading-lab/assets/dashboard.html) is reused
unchanged except for targeted, asserted edits that add a read-only connection to
the local ledger server, a live-gates panel, a runtime/data panel, and validation
for those optional report fields. Re-run after updating the skill template.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".claude/skills/pionex-trading-lab/assets/dashboard.html"
DST = ROOT / "dashboard/index.html"
TEMPLATE_SHA256 = "12a61a695560684939001ec5167a83f920a5f216b011861c4d91ce3c06677fcc"

html = SRC.read_text(encoding="utf-8")
assert hashlib.sha256(html.encode()).hexdigest() == TEMPLATE_SHA256, "skill template changed; review edits"


def rep(old, new):
    global html
    assert html.count(old) == 1, f"anchor not unique/missing: {old[:70]!r}"
    html = html.replace(old, new)


# --- markup: extra panels after the operational-state card
rep('<p class="soft" id="opReason" style="margin-top:12px">No service heartbeat received. This page cannot pause or close exchange positions.</p></div>\n</section>',
    '<p class="soft" id="opReason" style="margin-top:12px">No service heartbeat received. This page cannot pause or close exchange positions.</p></div>\n'
    '<div class="ext-panels" id="extPanels" hidden>'
    '<div class="card"><div class="panel-head"><h2>Live-trading gates</h2><span class="badge" id="gatesBadge">LIVE DISABLED</span></div>'
    '<div id="gateRows"></div><p class="soft" style="margin-top:12px">Live orders stay disabled until every gate passes and the user\'s authorization covers the exact account, capital, instruments, and mandate. This page cannot enable trading.</p></div>'
    '<div class="card"><div class="panel-head"><h2>Runtime &amp; data</h2><span class="badge" id="connBadge">NOT CONNECTED</span></div><div id="runtimeRows"></div></div></div>\n</section>')
rep('<button class="quiet" id="templateBtn">Download empty report</button><button class="quiet" id="clearBtn">Clear this view</button>',
    '<button class="quiet" id="templateBtn">Download empty report</button><button class="quiet" id="clearBtn">Clear this view</button><button class="quiet" id="reconnectBtn" hidden>Reconnect to ledger</button>')
rep('Continuous updates require your agent to connect an authenticated reporting service. Never enter a Pionex API key here.',
    'When this page is opened from the local <code>pionex_lab serve</code> URL, it polls that authenticated, read-only ledger endpoint instead. Never enter a Pionex API key here.')

# --- styles for the added panels (responsive; long values wrap instead of overflowing)
rep("[hidden]{display:none!important}",
    ".ext-panels{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;margin-top:18px}"
    ".ext-panels .row span{overflow-wrap:anywhere;min-width:0}.ext-panels .row span:last-child{max-width:62%}"
    "#gateRows .row>span:last-child{flex:none;white-space:nowrap;overflow-wrap:normal;font-size:.8rem;font-weight:600}"
    "@media(max-width:980px){.ext-panels{grid-template-columns:minmax(0,1fr)}}[hidden]{display:none!important}")

# --- script: state
rep("let active=null;", "let active=null,connected=false;const conn={token:null,timer:null,lastOk:0,pollMs:10000,error:null};")

# --- validation of optional extensions
rep("str(r.human_comparison.note,'Human note');return r;",
    "str(r.human_comparison.note,'Human note');"
    "if(r.live_gates!=null){if(!Array.isArray(r.live_gates)||r.live_gates.length>50)fail('live_gates must be a short array');for(const g of r.live_gates){obj(g,'Gate');for(const k of ['gate','status','detail'])str(g[k],k)}}"
    "for(const k of ['risk_state','runtime'])if(r[k]!=null)obj(r[k],k);"
    "if(r.risk_state&&r.risk_state.authoritative_max_drawdown_pct!=null)num(r.risk_state.authoritative_max_drawdown_pct,'Authoritative drawdown',0,100);"
    "return r;")

# --- render: honest connection labels
rep("setText('modeBadge',demo?'DEMONSTRATION · SYNTHETIC':r.mode+' · IMPORTED SNAPSHOT');",
    "setText('modeBadge',demo?'DEMONSTRATION · SYNTHETIC':connected?(connStale()?r.mode+' · CONNECTION LOST':r.mode+' · CONNECTED LEDGER (READ-ONLY)'):r.mode+' · IMPORTED SNAPSHOT');")
rep("let message=demo?'These figures are invented to demonstrate the dashboard. No money has been earned.':c.flows?",
    "let message=demo?'These figures are invented to demonstrate the dashboard. No money has been earned.':connected?(connStale()?'The ledger endpoint has not answered recently; figures below may be out of date.':'Read-only connection to the local canonical paper ledger. Fills are simulated on later observed quotes; order requests are Pionex dry-run previews and are never sent. No exchange account is connected.'):c.flows?")
rep("(demo?'Demonstration only':c.flows?'Cash-flow exception':'Viewing a report snapshot')",
    "(demo?'Demonstration only':connected?(connStale()?'Connection lost':'Connected to paper ledger'):c.flows?'Cash-flow exception':'Viewing a report snapshot')")
rep("setText('sourceNote',(demo?'SYNTHETIC EXAMPLE · ':r.mode+' REPORT · ')+r.source_label+' · Memory-only view; reload clears imported data.');}",
    "setText('sourceNote',(demo?'SYNTHETIC EXAMPLE · ':r.mode+' REPORT · ')+r.source_label+(connected?' · Polled read-only from the ledger server.':' · Memory-only view; reload clears imported data.'));renderExtensions(r);}")
rep("function importReport(data){let accepted=validate(data);active=JSON.parse(JSON.stringify(accepted));render();",
    "function importReport(data,viaConnection=false){let accepted=validate(data);if(!viaConnection)stopPolling();connected=viaConnection;active=JSON.parse(JSON.stringify(accepted));render();")
rep("return {mode:active.mode,equity_points:active.snapshots.length,trades:active.trades.length,connected:false}}",
    "return {mode:active.mode,equity_points:active.snapshots.length,trades:active.trades.length,connected:connected}}")
rep("$('clearBtn').onclick=()=>location.reload();",
    "$('clearBtn').onclick=()=>location.reload();$('reconnectBtn').onclick=()=>startPolling();")

# --- connection + extension rendering (appended before the browser-agent block)
EXT = r"""
function connStale(){return connected&&Date.now()-conn.lastOk>3*conn.pollMs}
function row(label,value){return '<div class="row"><span>'+esc(label)+'</span><span>'+esc(value)+'</span></div>'}
function renderExtensions(r){let show=!!(r.live_gates||r.runtime||r.risk_state);$('extPanels').hidden=!show;if(!show)return;
 let gates=r.live_gates||[];let pass=gates.filter(g=>g.status==='PASS').length;setText('gatesBadge',gates.length&&pass===gates.length?'ALL GATES PASS':'LIVE DISABLED · '+pass+'/'+gates.length+' PASS');
 $('gateRows').innerHTML=gates.length?gates.map(g=>'<div class="row"><span>'+esc(g.gate)+'<br><span class="soft">'+esc(g.detail)+'</span></span><span class="'+(g.status==='PASS'?'positive':'negative')+'">'+esc(g.status==='NOT_IMPLEMENTED'?'NOT BUILT':g.status)+'</span></div>').join(''):'<p class="soft">No gate report supplied.</p>';
 let rt=r.runtime||{},rs=r.risk_state||{};let rows='';
 rows+=row('Data source',rt.data_source?(rt.data_source+(rt.official_data_source?' (official Pionex API)':' (NOT Pionex)')):'none yet');
 rows+=row('Engine / collector heartbeat',(rt.engine_heartbeat_age_s==null?'—':rt.engine_heartbeat_age_s+'s')+' / '+(rt.collector_heartbeat_age_s==null?'—':rt.collector_heartbeat_age_s+'s'));
 rows+=row('Experiment window ends',rt.end_at||'clock not started');
 rows+=row('USD valuation',rt.fx||'—');
 let prev=rt.order_previews||{};rows+=row('Order requests (dry-run, never sent)',Object.keys(prev).length?Object.entries(prev).map(([k,v])=>v+' × '+k).join('; '):'none yet');
 let rd=rt.risk_decisions||{};rows+=row('Risk decisions',[(rd.approved||0)+' approved'].concat(Object.entries(rd.rejected||{}).map(([k,v])=>v+' '+k)).join(' · '));
 rows+=row('Active latches',(rs.latches&&rs.latches.length)?rs.latches.join(', '):'none');
 rows+=row('Authoritative max drawdown',rs.authoritative_max_drawdown_pct==null?'—':pct(rs.authoritative_max_drawdown_pct)+' ('+rs.snapshots_total+' snapshots)');
 rows+=row('Incidents / journal rows',(rt.incidents??'—')+' / '+(rt.journal_rows??'—'));
 if(rt.collector_last_error)rows+=row('Last collector error',rt.collector_last_error);
 rows+=row('Policy hash',rs.policy_hash?rs.policy_hash.slice(0,16)+'…':'—');
 $('runtimeRows').innerHTML=rows;setText('connBadge',connected?(connStale()?'CONNECTION LOST':'CONNECTED · READ-ONLY'):'SNAPSHOT');}
function stopPolling(){if(conn.timer){clearInterval(conn.timer);conn.timer=null}connected=false;$('reconnectBtn').hidden=!conn.token}
async function poll(){try{const res=await fetch('/api/report',{headers:{Authorization:'Bearer '+conn.token},cache:'no-store'});if(!res.ok){let t='';try{t=(await res.json()).error||''}catch{}throw new Error('Ledger endpoint HTTP '+res.status+(t?': '+t:''))}const data=await res.json();conn.lastOk=Date.now();conn.error=null;importReport(data,true)}catch(e){conn.error=e;if(active&&connected)render();showError(e)}}
function startPolling(){if(!conn.token)return;stopPolling();connected=true;$('reconnectBtn').hidden=true;poll();conn.timer=setInterval(poll,conn.pollMs)}
(function initConnection(){if(location.protocol==='file:')return;let m=location.hash.match(/token=([A-Za-z0-9_\-]{20,200})/);if(m){try{sessionStorage.setItem('pionexLabToken',m[1])}catch{}history.replaceState(null,'',location.pathname+location.search)}let t=m?m[1]:null;if(!t){try{t=sessionStorage.getItem('pionexLabToken')}catch{}}if(!t)return;conn.token=t;startPolling();setInterval(()=>{if(connected&&active)render()},5000)})();
"""
rep("// Optional browser-agent access uses the same validation and visible state.",
    EXT.strip() + "\n// Optional browser-agent access uses the same validation and visible state.")

DST.parent.mkdir(parents=True, exist_ok=True)
DST.write_text(html, encoding="utf-8")
print(f"wrote {DST} ({len(html)} bytes)")
