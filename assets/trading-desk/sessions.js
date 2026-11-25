/* Core-governed trading controls. Notifications never submit an order. */
(()=>{'use strict';
const el=id=>document.getElementById(id),deskToken=document.querySelector('meta[name="desk-token"]').content;
let rehearsalBusy=false;
let nonce='',proposal=null,loading=false,reviewGeneration=0,controls=null,readiness=null,readinessBusy=false;const seen=new Set();
async function call(action,body){const hosted=(document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/');const response=await fetch(hosted?'/api/trading/sessions'+(action==='status'?'':'/'+action):'/api/core-trading/'+action,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','x-desk-token':deskToken,'x-niblit-trading-nonce':nonce}:{},body:body?JSON.stringify(hosted?body:{...body,operator_nonce:nonce}):undefined,signal:AbortSignal.timeout(action==='status'?5000:120000)});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Core trading is unavailable');return data;}
function selection(){const adapter=el('environment').value;const remote=adapter==='exness_demo';return {adapter,symbol:el('core-execution-symbol').value.trim()||el(remote?'exness-symbol':adapter==='mt5'?'mt5-symbol':'pair').value,seconds:Number(el(remote?'exness-minutes':'auto-minutes').value||30)*60,limits:{max_entries:Number(el(remote?'exness-entries':'auto-entries').value||3),risk_cash:Number(el(remote?'exness-risk-cash':'core-risk-cash').value),risk_fraction:Number(el(remote?'exness-risk-percent':'core-risk-percent').value)/100,max_margin_fraction:Number(el(remote?'exness-margin-percent':'core-margin-percent').value)/100,max_positions:Number(el(remote?'exness-positions':'core-positions').value),...(adapter==='mt5'||remote?{max_volume:Number(el(remote?'exness-volume':'core-demo-volume').value)}:{})}};}
function quiet(){const start=el('core-quiet-from').value,end=el('core-quiet-to').value;if(!start||!end||start===end)return false;const now=new Date(),current=now.toTimeString().slice(0,5);return start<end?current>=start&&current<end:current>=start||current<end;}
function alertTitle(event){if(event.kind==='execution_result')return (event.payload.action==='open'?'Entry':'Exit')+' '+(event.payload.result?.state||'unconfirmed');if(event.kind==='reconciliation')return 'Position '+(event.payload.evidence?.state||'unconfirmed');return ({signal:'Strategy signal',mt5_connection_changed:'MT5 connection changed',strategy_disagreement:'Strategies disagree',risk_limit:'Risk limit reached',session_activated:'Demo session activated',session_stopped:'Session stopped',emergency_stop:'Emergency stop',session_expired:'Session expired',trading_error:'Trading error'})[event.kind]||event.kind;}
function alertDetail(body){const evidence=body.evidence||{};const net=typeof evidence.realized_net==='number'?` · realized ${evidence.realized_net} ${evidence.currency||''}`:'';return (body.assessment?.selection_reason||body.reason||body.error||body.notice||body.result?.state||evidence.state||'Inspect the recorded evidence in Market Desk.')+net;}
function showAlert(event){if(seen.has(event.id)||!event.alert||event.delivered)return;seen.add(event.id);
 if(!('Notification'in window)||Notification.permission!=='granted'||quiet()||Date.now()/1000-event.created>120)return;
 const body=event.payload;try{const popup=new Notification('Niblit · '+alertTitle(event),{body:`${body.symbol||''} · ${body.environment||'Core session'}\n${alertDetail(body)}`,tag:event.id});popup.onshow=()=>{void call('alerts/'+event.id+'/delivered',{}).catch(()=>{});};popup.onclick=()=>{window.focus();el('core-trading').scrollIntoView({behavior:'smooth'});popup.close();};}catch(_){/* Durable alert stays available in the list. */}}
let lastAccountStatus=null;
function renderAccountRecords(data) {
 const registry=data.mt5_accounts, selector=el('core-mt5-record');
 if(!registry){el('core-mt5-active').textContent='MT5 account discovery unavailable';return;}
 const active=registry.active, previous=selector.value;
 const describe=a=>a.broker+' · '+a.login+' · '+a.server+' · '+a.environment.toUpperCase();
 const status=active?describe(active)+' · connected'+(active.environment==='demo'?' · demo authorization required':' · read-only'):'MT5 disconnected or account unverified';
 const funded=data.funded_preflight;
 const risk=funded?' · Funded preflight '+funded.decision+' · '+funded.breaker_state+' · '+funded.reasons.join(', '):' · Funded costs and policy unverified';
 const at=registry.last_transition?new Date(registry.last_transition*1000).toLocaleTimeString():'unavailable';
 el('core-mt5-active').textContent=status+' · last connection change '+at+risk;
 selector.replaceChildren(...registry.known.map(a=>{
   const option=document.createElement('option');option.value=a.identity;
   option.textContent=describe(a)+(a.identity===active?.identity?' (active)':a.verification==='configured'?' (configured, unverified)':' (historical)');
   return option;
 }));
 selector.value=registry.known.some(a=>a.identity===previous)?previous:active?.identity||registry.known[0]?.identity||'';
 const record=registry.known.find(a=>a.identity===selector.value);
 const verified=record?.last_verified?new Date(record.last_verified*1000).toLocaleString():'never observed';
 const history=(data.orders||[]).filter(o=>o.adapter==='mt5'&&o.account===selector.value).map(o=>{
   const stale=o.state==='open'&&o.account!==active?.identity?' · last recorded open; broker status unverified':'';
   return o.symbol+' · '+o.action+' · '+o.state+stale+' · '+o.id;
 });
 el('core-mt5-history').textContent=(record?'Last verified '+verified+'\n':'')+(history.join('\n')||'No Core order history for this account.');
}
el('core-mt5-record').onchange=()=>{if(lastAccountStatus)renderAccountRecords(lastAccountStatus);};
async function refresh(){if(loading)return;loading=true;try{const data=await call('status');nonce=data.operator_nonce;
 const remote=data.remote_gateway, remotePanel=el('remote-gateway-status');
 if(remotePanel){
   window.renderRemoteObservation(remote);
   if(remote?.verified && el('environment').value==='mt5' && controls?.platform_delivery_enabled?.mt5!==true){
     for(const id of ['core-propose','core-propose-close','core-activate','auto-start','core-observe'])el(id).disabled=true;
   }
 }

controls=data.execution_controls||{activation_available:false,review_available:false,blocker:'Core policy unavailable'};
 window.niblitDemoActivationAvailable=controls.activation_available===true;
 const recovery=controls.recovery||{};
 const pendingRecovery=recovery.broker_reconciliation_required?` · ${recovery.unresolved_orders_visible} historical broker delivery claim(s) require reconciliation on their original account`:'';

 el('core-deployment-policy').textContent=`${controls.mode||'UNKNOWN'} · ${controls.blocker||controls.delivery_blocker||'Verified demo transport required'}${pendingRecovery}. No automatic reset or retry.`;
 const selectedAdapter=el('environment').value;
 const selectedTransport=controls.platform_delivery_enabled?.[selectedAdapter]===true;
 const reasons=[...new Set([...(recovery.activation_blockers||[]),...(!selectedTransport?[`Selected ${selectedAdapter} demo transport is not verified or enabled`]:[])])];
 el('core-activation-readiness').textContent=selectedTransport&&reasons.length===0?'Execution prerequisites reported available; a fresh account-bound scope and final broker review are still required.':`Execution activation not ready for ${selectedAdapter}: ${reasons.join('; ')||'Complete a fresh readiness review'}. No broker execution was authorized.`;
 el('core-readiness').disabled=readinessBusy||!controls.review_available;
 el('core-rehearse').disabled=!(document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/')||rehearsalBusy;
 el('core-observe').disabled=Boolean(remote?.verified&&el('environment').value==='mt5');
 el('core-propose').disabled=!controls.review_available;
 el('core-propose-close').disabled=!controls.review_available;
 el('core-activate').disabled=!proposal||!controls.activation_available;
 lastAccountStatus=data;renderAccountRecords(data);el('core-session-state').textContent=remote?.verified?'REMOTE DEMO OBSERVATION · Local MT5 scope unavailable':'R14 DEMO EXECUTION · REAL-MONEY DISABLED · Account-bound scope required';
 el('core-session-list').textContent=data.sessions.map(s=>`${s.spec.adapter} ${s.spec.symbol} · ${s.spec.environment} · ${s.spec.account_binding?.login||s.spec.account} · ${s.state} · ${s.entries}/${s.spec.limits.max_entries} entries · ${s.expires?'expires '+new Date(s.expires*1000).toLocaleTimeString():'not activated; '+s.spec.seconds+'s begins on activation'}${s.reason?' · '+s.reason:''}`).join('\n')||'No session approved.';
 el('core-owned-orders').textContent=(data.orders||[]).filter(o=>o.adapter==='mt5'&&o.action==='open'&&o.state==='open').map(o=>o.symbol+' · Core order '+o.id).join('\n');
 el('core-observer-list').textContent=data.observers.map(o=>`${o.adapter} ${o.symbol} · ${o.running?'observing':'stopped'} · ${o.error||o.assessment?.selection_reason||'Awaiting first observation'} ${(o.assessment?.candidates||[]).map(c=>c.strategy+':'+c.side+(c.context?(' ['+Object.entries(c.context).map(([frame,data])=>frame+' '+(data.trend||data.status)).join(', ')+']'):'')).join(' · ')}`).join('\n');
 el('core-alerts').replaceChildren(...data.events.filter(e=>e.alert).slice(0,20).map(e=>{const row=document.createElement('p');row.textContent=`${new Date(e.created*1000).toLocaleTimeString()} · ${alertTitle(e)} · ${e.payload.symbol||''} · ${alertDetail(e.payload)} · ${e.delivered?'popup reported shown':'saved; popup not confirmed'}`;return row;}));data.events.slice().reverse().forEach(showAlert);
 if(window.renderBrokerView)window.renderBrokerView(data);
  }catch(e){el('core-session-state').textContent=e.message;controls=null;window.niblitDemoActivationAvailable=false;
 for(const id of ['core-readiness','core-rehearse','core-propose','core-propose-close','core-observe','core-activate'])el(id).disabled=true;
 el('core-deployment-policy').textContent='Core unavailable; no activation or scope review is available.';
 el('core-activation-readiness').textContent='Core unavailable; cannot verify execution prerequisites.';
 const remotePanel=el('remote-gateway-status');
 if(remotePanel){
 const previous=lastAccountStatus?.remote_gateway?.broker_observation;
 const unavailable={schema_version:'niblit.broker-observation/1',gateway:{status:'reconnecting'},balances:{},
 freshness:previous?'stale':'unavailable',last_verified:previous?.last_verified||(previous?.account?{
 ...previous.balances,account:previous.account,breaker:lastAccountStatus?.remote_gateway?.breaker,observed_at:previous.observation_at}:null),inventory_fresh:false,
 reconciliation:{status:'UNKNOWN'},execution_disabled_reasons:['Core unavailable','funded_execution_disabled'],warnings:[]};
 window.renderRemoteObservation({broker_observation:unavailable});
 remotePanel.textContent='CORE UNAVAILABLE · remote observations unavailable · REAL-MONEY EXECUTION DISABLED';
 }
 }finally{loading=false;}}
async function propose(closeOrderId=null){try{await refresh();await reviewReadiness();const scope=selection();if(closeOrderId)scope.close_order_id=closeOrderId;const generation=reviewGeneration;const reviewed=await call('propose',scope);if(generation!==reviewGeneration)return;proposal=reviewed;el('core-proposal').textContent=JSON.stringify({account:proposal.spec.account,environment:proposal.spec.environment,adapter:proposal.spec.adapter,symbol:proposal.spec.symbol,strategies:proposal.spec.strategies,duration_seconds:proposal.spec.seconds,limits:proposal.spec.limits,position_actions:proposal.spec.position_actions,account_binding:proposal.spec.account_binding,position_identifier:proposal.spec.position_identifier,close_order_id:proposal.spec.close_order_id,notice:'Broker stops remain after expiry. No live money. No session is active until you activate this exact scope.'},null,2);el('core-activate').disabled=!controls?.activation_available;}catch(e){el('core-session-state').textContent=e.message;}}
el('core-propose').onclick=()=>propose();
el('core-propose-close').onclick=()=>{
 const id=el('core-close-order').value.trim();
 if(!/^[a-f0-9]{64}$/.test(id)){el('core-session-state').textContent='Enter the full Core order ID.';return;}
 return propose(id);
};
el('core-observe').onclick=async()=>{try{await refresh();await call('observe',selection());await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-observe-many').onclick=async()=>{try{await refresh();const adapter=el('environment').value;
 const symbols=[...new Set(el('core-watch-symbols').value.split(/[,;\n]+/).map(s=>s.trim()).filter(Boolean))];
 if(!symbols.length||symbols.length>12)throw Error('Select 1–12 exact broker symbols');
 const result=await call('observe-many',{adapter,symbols});
 el('core-session-state').textContent=`Observing ${result.observers} ${adapter} markets; independent analysis, no order submitted.`;
 await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-activate').onclick=async()=>{if(!proposal)return;const message='Activate this exact bounded demo scope? Eligible demo orders and owned-position exits may run until expiry.';if(!window.confirm(message))return;try{await call('activate',{id:proposal.id,spec_hash:proposal.spec_hash,acknowledgement:'ACTIVATE_BOUNDED_DEMO_SESSION'});proposal=null;el('core-activate').disabled=true;await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-stop').onclick=async()=>{try{await call('stop',{id:null});await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-notifications').onclick=async()=>{if(!('Notification'in window)){el('core-session-state').textContent='Popup notifications unavailable here; durable alerts remain in Market Desk.';return;}const permission=await Notification.requestPermission();el('core-session-state').textContent='Desktop notification permission: '+permission;};
for(const id of ['core-quiet-from','core-quiet-to']){el(id).value=localStorage.getItem('niblit-'+id)||'';el(id).onchange=()=>localStorage.setItem('niblit-'+id,el(id).value);}
for(const id of ['core-execution-symbol','core-demo-volume','auto-entries','auto-minutes','mt5-symbol','environment','pair','core-risk-cash','core-risk-percent','core-margin-percent','core-positions','exness-symbol','exness-minutes','exness-volume','exness-entries','exness-risk-cash','exness-risk-percent','exness-margin-percent','exness-positions']){for(const event of ['input','change'])el(id).addEventListener(event,()=>{reviewGeneration++;proposal=null;readiness=null;el('core-activate').disabled=true;el('core-proposal').textContent='Settings changed. Review a fresh scope.';if(id==='environment')void refresh();});}
el('core-wave-15').onclick=()=>{el('auto-minutes').value='15';el('auto-minutes').dispatchEvent(new Event('input'));};
// Preserve the familiar bounded-start control, now routed through Core review.
el('auto-start').onclick=()=>propose();
const stopLegacyResearch=el('auto-stop').onclick;
el('auto-stop').onclick=async()=>{await el('core-stop').onclick();if(stopLegacyResearch)await stopLegacyResearch();};
async function reviewReadiness(){
 const generation=reviewGeneration;const result=await call('readiness',selection());
 if(generation!==reviewGeneration)return;
 readiness=result;el('core-readiness-result').textContent=JSON.stringify(result,null,2);return result;
}
el('core-readiness').onclick=async()=>{const b=el('core-readiness');readinessBusy=true;b.disabled=true;try{await refresh();await reviewReadiness();await refresh();}catch(e){readiness=null;el('core-readiness-result').textContent=e.message;}finally{readinessBusy=false;b.disabled=!controls?.review_available;}};

el('core-rehearse').disabled=!(document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/');
el('core-rehearse').onclick=async()=>{
 const b=el('core-rehearse');rehearsalBusy=true;b.disabled=true;
 try{
  if(!(document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/'))throw Error('Use the installed Core-hosted Trading page for this rehearsal.');
  el('core-rehearsal-result').textContent='Running the existing Core/adapters with intercepted delivery. No external order authority is granted.';
  const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:'Run the governed execution rehearsal',model:'niblit'}),signal:AbortSignal.timeout(180000)});
  const value=await r.json();if(!r.ok)throw Error(value.detail||value.error||'Rehearsal unavailable');
  el('core-rehearsal-result').textContent=value.reply||'UNKNOWN';await refresh();
 }catch(e){el('core-rehearsal-result').textContent=e.message;}finally{rehearsalBusy=false;b.disabled=!controls;}
};
setInterval(()=>{if(!document.hidden)void refresh();},5000);void refresh();
})();


/* Niblit R14 modern Market Desk presentation — no broker write paths. */
(() => {
 "use strict";
 const q = id => document.getElementById(id);
 const instrument=q("core-execution-symbol");
 const recap=q("desk-blocker-summary");
 let lastReview="", lastStatusAt=0, refreshing=false;
 const text=(node,val)=>{if(node && node.textContent!==val)node.textContent=val};
 const el=(tag,cls,content)=>{
   const n=document.createElement(tag);
   if(cls)n.className=cls;
   if(content!==undefined)n.textContent=String(content);
   return n;
 };
 function humanIssue(b) {
   const code=b.code||"",reason=b.reason||"";
   if(code==="instrument_scope")
     return "This broker symbol is outside R14's reviewed demo execution scope. Choose ETHUSDm in Execution-controller instrument. BTCUSDm remains observable.";
   if(code==="risk_preflight"&&/capacity|exposure/i.test(reason))
     return "The BTCUSDm position already uses one account position slot. Review a maximum of 2 simultaneous positions for an ETHUSDm session; the unchanged risk/margin checks still apply.";
   if(code==="no_scoped_authority")
     return "No session is active yet. After a valid readiness review, propose and explicitly activate the exact demo scope.";
   if(code==="consensus_abstention"||code==="entry_preflight_pending")
     return "No qualifying entry now. A session can observe until a valid strategy setup is confirmed; observation is not an order.";
   return reason||code||"Unknown review response";
 }
 function renderReview(raw){
   if(!raw||raw[0]!=="{")return;
   let data;
   try{data=JSON.parse(raw);}catch{return;}
   if(!data||!Array.isArray(data.blockers)||!Object.prototype.hasOwnProperty.call(data,"activation_eligible"))return;
   const node=q("core-readiness-result");
   if(!node)return;
   lastReview=raw;
   const eligible=data.activation_eligible===true;
   const header=el("div","readiness-status",eligible?"Broker review passed — proposal available":"Review requires attention");
   const badge=el("span","readiness-badge"+(eligible?" ok":""),eligible?"Ready to propose":"Review required");
   header.append(badge);
   const intro=el("p","",eligible?
     "Account, transport and session rules permit a proposal. Nothing has been activated and no broker order has been sent.":
     "The selected scope cannot be activated as shown. Resolve the applicable items below, then review again.");
   const list=el("ul");
   for(const b of data.blockers)list.append(el("li","",humanIssue(b)));
   if(!data.blockers.length)list.append(el("li","","No blockers returned by Core."));
   const details=el("details","desk-evidence");
   details.append(el("summary","", "Complete broker / strategy evidence (JSON)"));
   details.append(el("pre","",raw));
   node.replaceChildren(header,intro,list,details);
   text(recap,eligible?
      "ETHUSDm is ready for an account-bound proposal. Select “2 · Propose reviewed demo session”, then “3 · Activate confirmed demo session”. A strategy must still qualify before an entry occurs.":
      data.blockers.map(humanIssue).filter((x,i,a)=>a.indexOf(x)===i).slice(0,3).join("\n"));
 }
 const reviewNode=q("core-readiness-result");
 if(reviewNode){
   const observer=new MutationObserver(()=>{
     const raw=reviewNode.textContent.trim();
     if(raw!==lastReview)renderReview(raw);
   });
   observer.observe(reviewNode,{subtree:true,childList:true,characterData:true});
 }
 async function status(){
   if(refreshing)return;
   refreshing=true;
   try{
     const r=await fetch("/api/trading/sessions",{
       method:"GET",headers:{"Accept":"application/json"},
       credentials:"same-origin",signal:AbortSignal.timeout(9000)});
     if(!r.ok)throw Error("Core status unavailable");
     const data=await r.json();
     text(q("desk-core-health"),"Online");
     const active=(data.sessions||[]).filter(s=>s.state==="active");
     text(q("desk-active-count"),String(active.length));
     const account=data.mt5_accounts?.active;
     text(q("desk-account-mode"),account?.environment==="demo"?"DEMO CONNECTED":"Verification needed");
     text(q("desk-execution-market"),instrument?.value.trim()||"Not selected");
     const chip=q("desk-activation-chip");
     if(chip){
       chip.textContent=active.length?"Active · "+active.map(s=>s.spec?.symbol||"MT5").join(", "):"Awaiting activation";
       chip.classList.toggle("active",active.length>0);
     }
     const selected=instrument?.value.trim();
     if(selected==="BTCUSDm"){
       text(recap,"BTCUSDm is available for observation, not R14 demo entry. R14 currently permits ETHUSDm execution. Select ETHUSDm and review the two-position scope.");
     }else if(!active.length&&!lastReview){
       text(recap,"ETHUSDm · 0.10 lot ceiling · 60 minutes · 2-position account capacity. One BTCUSDm position already exists. Click “1 · Review broker and scope”.");
     }
     lastStatusAt=Date.now();
   }catch{
     text(q("desk-core-health"),"Reconnecting");
     if(!lastStatusAt)text(recap,"R14 Core is unavailable. No session can be activated until it reconnects.");
   }finally{refreshing=false}
 }
 instrument?.addEventListener("input",()=>{
   lastReview="";
   text(q("desk-execution-market"),instrument.value.trim()||"Not selected");
   text(recap,"Scope changed. Run a fresh broker review before proposing or activating.");
 });
 setInterval(()=>{if(!document.hidden)void status()},12000);
 void status();
})();



/* Read-only cognition evidence viewer for the canonical R14 Market Desk. */
(() => {
  "use strict";
  const root = document.getElementById("cognition-proof");
  if (!root) return;
  const byId = id => document.getElementById(id);
  let busy=false;
  function set(id, value) {
    const node=byId(id);
    if (node) node.textContent = String(value);
  }
  function row(label,value) {
    const div=document.createElement("div");
    div.className="cognition-evidence-row";
    const key=document.createElement("span");
    const val=document.createElement("strong");
    key.textContent=label;
    val.textContent=String(value??"Unavailable");
    div.append(key,val);
    return div;
  }
  function date(value) {
    const d=new Date(Number(value)*1000);
    return Number.isFinite(d.getTime()) ? d.toLocaleString() : "Time unavailable";
  }
  async function refresh() {
    if (busy) return;
    busy=true;
    const button=byId("cognition-refresh");
    if (button) button.disabled=true;
    try {
      const response=await fetch("/api/trading/sessions",{
        headers:{"Accept":"application/json"},
        credentials:"same-origin",
        signal:AbortSignal.timeout(12000)});
      if(!response.ok) throw new Error("Core replied "+response.status);
      const status=await response.json();
      const events=Array.isArray(status.events)?status.events.slice(0,100):[];
      const kind=name=>events.filter(e=>e&&e.kind===name);
      const signals=kind("signal");
      const reversals=kind("position_reversal_evaluation");
      const outcomes=kind("trading_outcome");
      set("cognition-signal-count",signals.length);
      set("cognition-reversal-count",reversals.length);
      set("cognition-outcome-count",outcomes.length);
      set("cognition-data-scope","Latest "+events.length+" Core events · Not a lifetime total");
      const latest=signals[0];
      const assessment=latest?.payload?.assessment||{};
      const marketThesis=assessment.market_thesis||{};
      set("cognition-current-strategy",assessment.strategy||"No selected strategy");
      set("cognition-current-direction",assessment.side||"No entry");
      set("cognition-current-thesis",marketThesis.classification||"No evidence-linked thesis");
      set("cognition-current-reason",assessment.selection_reason||"No recent rule selection");
      const selected=byId("cognition-votes");
      if(selected) {
        selected.replaceChildren();
        const candidates=Array.isArray(assessment.candidates)?assessment.candidates:[];
        for(const candidate of candidates.slice(0,16)){
          if(!candidate || typeof candidate!=="object")continue;
          selected.append(row(String(candidate.strategy||"Unidentified strategy"),
                              String(candidate.side||"wait").toUpperCase()));
        }
        if(!selected.children.length)selected.append(row("Strategy votes","Not available"));
      }
      const rev=byId("cognition-last-reversal");
      if(rev){
        rev.replaceChildren();
        const latestReversal=reversals[0];
        if(latestReversal) {
          const payload=latestReversal.payload||{};
          const report=payload.report||{};
          rev.append(
            row("Instrument",payload.symbol||"Unknown"),
            row("Evaluation",String(report.action||"unknown").toUpperCase()),
            row("Evidence reason",report.reason||"Unspecified"),
            row("Recorded",date(latestReversal.created)));
        } else rev.append(row("Exit cognition","No recent reversal evaluations in this event window"));
      }
      const history=byId("cognition-verified-outcomes");
      if(history){
        history.replaceChildren();
        for(const outcome of outcomes.slice(0,5)){
          const p=outcome.payload||{};
          const e=p.evidence||{};
          const perf=p.performance||{};
          const item=document.createElement("div");
          item.className="cognition-outcome";
          const net=(typeof e.realized_net==="number" && Number.isFinite(e.realized_net))?
            e.realized_net.toFixed(2)+" account currency units":"Not broker verified";
          const nr=(typeof perf.net_realized_r==="number" && Number.isFinite(perf.net_realized_r))?
            perf.net_realized_r.toFixed(3)+" R":"R unavailable";
          item.append(row(String(p.symbol||"MT5")+" · "+String(p.strategy||"unknown"),
                          net+" · "+nr));
          history.append(item);
        }
        if(!history.children.length)history.append(row("Broker outcomes","None in this event window"));
      }
      set("cognition-proof-status","Read-only Core evidence · "+new Date().toLocaleTimeString());
    }catch(error) {
      set("cognition-proof-status","Core evidence unavailable: "+String(error?.message||error));
    }finally{
      busy=false;
      if(button)button.disabled=false;
    }
  }
  byId("cognition-refresh")?.addEventListener("click",refresh);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh()});
  setInterval(()=>{if(!document.hidden)refresh()},20000);
  refresh();
})();

