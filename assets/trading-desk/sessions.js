/* Core-governed trading controls. Notifications never submit an order. */
(()=>{'use strict';
const el=id=>document.getElementById(id),deskToken=document.querySelector('meta[name="desk-token"]').content;
let nonce='',proposal=null,loading=false,reviewGeneration=0;const seen=new Set();
async function call(action,body){const hosted=(document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/');const response=await fetch(hosted?'/api/trading/sessions'+(action==='status'?'':'/'+action):'/api/core-trading/'+action,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','x-desk-token':deskToken,'x-niblit-trading-nonce':nonce}:{},body:body?JSON.stringify(hosted?body:{...body,operator_nonce:nonce}):undefined,signal:AbortSignal.timeout(action==='status'?5000:120000)});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Core trading is unavailable');return data;}
function selection(){const adapter=el('environment').value;return {adapter,symbol:el(adapter==='mt5'?'mt5-symbol':'pair').value,seconds:Number(el('auto-minutes').value||30)*60,limits:{max_entries:Number(el('auto-entries').value||3),risk_cash:Number(el('core-risk-cash').value),risk_fraction:Number(el('core-risk-percent').value)/100,max_margin_fraction:Number(el('core-margin-percent').value)/100,max_positions:Number(el('core-positions').value),...(adapter==='mt5'?{max_volume:Number(el('core-demo-volume').value)}:{})}};}
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
   if(remote?.configured && el('environment').value==='mt5'){
     for(const id of ['core-propose','core-propose-close','core-activate','auto-start','core-observe'])el(id).disabled=true;
   }
 }

lastAccountStatus=data;renderAccountRecords(data);el('core-session-state').textContent=remote?.configured?'REAL-MONEY EXECUTION DISABLED · Remote observation only':data.emergency_stopped?'Emergency stop is latched. Observation and reconciliation continue.':'REAL-MONEY EXECUTION DISABLED — r9.1 VERIFICATION MODE · Explicit demo activation required';
 el('core-session-list').textContent=data.sessions.map(s=>`${s.spec.adapter} ${s.spec.symbol} · ${s.spec.environment} · ${s.spec.account_binding?.login||s.spec.account} · ${s.state} · ${s.entries}/${s.spec.limits.max_entries} entries · expires ${new Date(s.expires*1000).toLocaleTimeString()}${s.reason?' · '+s.reason:''}`).join('\n')||'No session approved.';
 el('core-owned-orders').textContent=(data.orders||[]).filter(o=>o.adapter==='mt5'&&o.action==='open'&&o.state==='open').map(o=>o.symbol+' · Core order '+o.id).join('\n');
 el('core-observer-list').textContent=data.observers.map(o=>`${o.adapter} ${o.symbol} · ${o.running?'observing':'stopped'} · ${o.error||o.assessment?.selection_reason||'Awaiting first observation'} ${(o.assessment?.candidates||[]).map(c=>c.strategy+':'+c.side+(c.context?(' ['+Object.entries(c.context).map(([frame,data])=>frame+' '+(data.trend||data.status)).join(', ')+']'):'')).join(' · ')}`).join('\n');
 el('core-alerts').replaceChildren(...data.events.filter(e=>e.alert).slice(0,20).map(e=>{const row=document.createElement('p');row.textContent=`${new Date(e.created*1000).toLocaleTimeString()} · ${alertTitle(e)} · ${e.payload.symbol||''} · ${alertDetail(e.payload)} · ${e.delivered?'popup reported shown':'saved; popup not confirmed'}`;return row;}));data.events.slice().reverse().forEach(showAlert);
 if(window.renderBrokerView)window.renderBrokerView(data);
  }catch(e){el('core-session-state').textContent=e.message;
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
async function propose(closeOrderId=null){try{await refresh();const scope=selection();if(closeOrderId)scope.close_order_id=closeOrderId;const generation=reviewGeneration;const reviewed=await call('propose',scope);if(generation!==reviewGeneration)return;proposal=reviewed;el('core-proposal').textContent=JSON.stringify({account:proposal.spec.account,environment:proposal.spec.environment,adapter:proposal.spec.adapter,symbol:proposal.spec.symbol,strategies:proposal.spec.strategies,duration_seconds:proposal.spec.seconds,limits:proposal.spec.limits,position_actions:proposal.spec.position_actions,account_binding:proposal.spec.account_binding,position_identifier:proposal.spec.position_identifier,close_order_id:proposal.spec.close_order_id,notice:'Broker stops remain after expiry. No live money. No session is active until you activate this exact scope.'},null,2);el('core-activate').disabled=false;}catch(e){el('core-session-state').textContent=e.message;}}
el('core-propose').onclick=()=>propose();
el('core-propose-close').onclick=()=>{
 const id=el('core-close-order').value.trim();
 if(!/^[a-f0-9]{64}$/.test(id)){el('core-session-state').textContent='Enter the full Core order ID.';return;}
 return propose(id);
};
el('core-observe').onclick=async()=>{try{await refresh();await call('observe',selection());await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-activate').onclick=async()=>{if(!proposal||!window.confirm('Activate this exact bounded demo scope? Orders and owned-position exits may run until its expiry.'))return;try{await call('activate',{id:proposal.id,spec_hash:proposal.spec_hash,acknowledgement:'ACTIVATE_BOUNDED_DEMO_SESSION',clear_emergency_stop:el('core-clear-stop').checked});proposal=null;el('core-activate').disabled=true;await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-stop').onclick=async()=>{try{await call('stop',{emergency:false});await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-emergency').onclick=async()=>{try{await call('stop',{emergency:true});await refresh();}catch(e){el('core-session-state').textContent=e.message;}};
el('core-notifications').onclick=async()=>{if(!('Notification'in window)){el('core-session-state').textContent='Popup notifications unavailable here; durable alerts remain in Market Desk.';return;}const permission=await Notification.requestPermission();el('core-session-state').textContent='Desktop notification permission: '+permission;};
for(const id of ['core-quiet-from','core-quiet-to']){el(id).value=localStorage.getItem('niblit-'+id)||'';el(id).onchange=()=>localStorage.setItem('niblit-'+id,el(id).value);}
for(const id of ['core-demo-volume','auto-entries','auto-minutes','mt5-symbol','environment','pair','core-risk-cash','core-risk-percent','core-margin-percent','core-positions']){for(const event of ['input','change'])el(id).addEventListener(event,()=>{reviewGeneration++;proposal=null;el('core-activate').disabled=true;el('core-proposal').textContent='Settings changed. Review a fresh scope.';});}
el('core-wave-15').onclick=()=>{el('auto-minutes').value='15';el('auto-minutes').dispatchEvent(new Event('input'));};
// Preserve the familiar bounded-start control, now routed through Core review.
el('auto-start').onclick=()=>propose();
const stopLegacyResearch=el('auto-stop').onclick;
el('auto-stop').onclick=async()=>{await el('core-stop').onclick();if(stopLegacyResearch)await stopLegacyResearch();};
setInterval(()=>{if(!document.hidden)void refresh();},5000);void refresh();
})();
