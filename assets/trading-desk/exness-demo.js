/* Existing Core session authority; this view never talks directly to the VPS. */
(()=>{'use strict';
const el=id=>document.getElementById(id);let nonce='',proposal=null,busy=false,last=null,reviewGeneration=0;
async function call(path,body){const r=await fetch('/api/trading/'+path,{method:body?'POST':'GET',
 headers:body?{'Content-Type':'application/json','x-niblit-trading-nonce':nonce}:{},
 body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});
 const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Core demo dependency unavailable');return d;}
function scope(){return {adapter:'exness_demo',symbol:el('exness-symbol').value,
 seconds:Number(el('exness-minutes').value)*60,limits:{max_entries:Number(el('exness-entries').value),max_positions:Number(el('exness-positions').value),max_volume:Number(el('exness-volume').value),risk_cash:Number(el('exness-risk-cash').value),risk_fraction:Number(el('exness-risk-percent').value)/100,max_margin_fraction:Number(el('exness-margin-percent').value)/100}};}
function disable(){for(const id of ['exness-observe','exness-propose','exness-activate'])el(id).disabled=true;
 el('exness-market').textContent='CURRENT EXNESS MARKET DATA UNAVAILABLE'+(last?' · Last readback '+new Date(last.checked_at*1000).toLocaleString():'');
 el('exness-inventory').textContent='CURRENT EXNESS INVENTORY UNAVAILABLE';el('exness-protection').textContent='CURRENT CRYPTO PROTECTION PREVIEW UNAVAILABLE';}
async function refresh(){if(busy)return;busy=true;try{
 const d=await call('sessions');nonce=d.operator_nonce;const s=d.remote_demo;
 el('exness-demo').hidden=!s?.configured;if(!s?.configured)return;
 if(!s.verified){disable();el('exness-execution-state').textContent='CORE DEMO EXECUTION BLOCKED · Exness demo identity unavailable';el('exness-status').textContent='EXNESS DEMO UNAVAILABLE · No current account or prices verified';if(window.renderBrokerView)window.renderBrokerView(d);return;}
 const cap=Math.min(.10,Number(s.max_volume)||.01);el('exness-volume').max=String(cap);
 el('exness-volume-rules').textContent=`Verified demo adapter ceiling ${cap} lots. Broker min/step and cash risk still apply. This is a maximum, not a guaranteed size. A changed amount needs a fresh review.`;
 const previous=el('exness-symbol').value;el('exness-symbol').replaceChildren(...s.symbols.map(name=>{
 const o=document.createElement('option');o.value=name;o.textContent=name;return o;}));
 if(s.symbols.includes(previous))el('exness-symbol').value=previous;
 el('exness-status').textContent=`MT5 DEMO VERIFIED · ${s.account.broker} · ${s.account.login} · ${s.account.server}\nVirtual balance ${s.balance} · equity ${s.equity} · free margin ${s.free_margin}\nAlgo Trading ${s.terminal_trade_allowed?'ON':'OFF'} · persistent demo stop ${s.emergency_stopped?'LATCHED':'off'} · uncertain deliveries ${s.unresolved_deliveries}\nREAL-MONEY EXECUTION DISABLED · No automatic activation after restart`;
 if(window.renderBrokerView)window.renderBrokerView(d);else el('mode').textContent='VPS · XM LIVE BLOCKED · EXNESS DEMO';
 const executionReady=s.terminal_trade_allowed===true&&s.account_trade_allowed===true&&s.python_tradeapi_disabled===false&&!s.emergency_stopped&&!s.unresolved_deliveries;
 const active=(d.sessions||[]).find(x=>x.spec.adapter==='exness_demo'&&x.state==='active'&&x.expires>Date.now()/1000);
 el('exness-execution-state').textContent=active?`CORE DEMO EXECUTION ENABLED · ${active.spec.symbol} · ${active.entries}/${active.spec.limits.max_entries} entries used · expires ${new Date(active.expires*1000).toLocaleString()}`:
  executionReady?'CORE DEMO EXECUTION OFF · Review and enable a bounded session below.':'CORE DEMO EXECUTION BLOCKED · Verify Algo Trading, API permissions, emergency stop and delivery reconciliation.';
 el('exness-observe').disabled=false;el('exness-propose').disabled=!executionReady;
 if(!executionReady)el('exness-activate').disabled=true;
 el('exness-sessions').textContent=d.sessions.filter(x=>x.spec.adapter==='exness_demo').map(x=>`${x.spec.symbol} · ${x.state} · ${x.entries}/${x.spec.limits.max_entries} entries · expires ${new Date(x.expires*1000).toLocaleString()}${x.reason?' · '+x.reason:''}`).join('\n')||'No Exness demo session approved.';
 el('exness-orders').textContent=(d.orders||[]).filter(x=>x.adapter==='exness_demo').map(x=>`${x.symbol} · ${x.action} · ${x.state}\n${x.result||'No broker receipt yet'}`).join('\n')||'No Exness Core delivery receipts.';
 el('exness-strategies').textContent=d.observers.filter(x=>x.adapter==='exness_demo').map(x=>`${x.symbol} · ${x.error||x.assessment?.selection_reason||'Awaiting observation'}\n${(x.assessment?.candidates||[]).map(c=>c.strategy+': '+c.side).join('\n')}`).join('\n');
 const m=await call('exness-demo/market?symbol='+encodeURIComponent(el('exness-symbol').value));last=m;
 const q=m.quote||{},p=m.specification||{};
 el('exness-market').textContent=`${m.symbol} · ${q.fresh?'Advancing broker quote':'QUOTE FRESHNESS UNVERIFIED'}\n${q.fresh?'Bid '+q.bid+' · ask '+q.ask+' · spread '+q.spread:'Current bid/ask unavailable'}\nBroker tick time ${q.timestamp?new Date(q.timestamp*1000).toISOString():'UNKNOWN'}\nReceived ${new Date(m.checked_at*1000).toLocaleString()}\nMinimum ${p.volume_min??'UNKNOWN'} · step ${p.volume_step??'UNKNOWN'} · contract ${p.trade_contract_size??'UNKNOWN'} · tick size ${p.trade_tick_size??'UNKNOWN'}\nCurrency ${p.currency_base??'UNKNOWN'}/${p.currency_profit??'UNKNOWN'} · stops ${p.trade_stops_level??'UNKNOWN'} points · freeze ${p.trade_freeze_level??'UNKNOWN'} points\nVerified adapter cap ${s.max_volume} lots · reviewed session cap may be lower · commission schedule UNKNOWN\nLast completed M5 candles (broker timestamps):\n${(m.candles||[]).slice(-10).map(b=>new Date(b.timestamp*1000).toISOString()+'  O '+b.open+' H '+b.high+' L '+b.low+' C '+b.close).join('\n')}`;
 el('exness-inventory').textContent=`Current demo positions: ${m.positions.length}\n${m.positions.map(p=>`${p.ticket} · ${p.symbol} · ${p.type===0?'buy':'sell'} · ${p.volume} lots · SL ${p.sl} · TP ${p.tp} · floating ${p.profit}`).join('\n')}\nPending orders: ${m.pending_order_count}`;
 const protection=m.protection_preview;
 el('exness-protection').textContent=protection?.status==='available'?
  `CRYPTO PROTECTION · ${m.protection_policy.version}\nClosed M5 volatility + recent swing structure + spread/broker distance buffers\nPreview uses the default 2x ATR rule; the selected strategy's reviewed rule may use 2.5x ATR.\n${['buy','sell'].map(side=>{const p=protection[side];return `${side.toUpperCase()} · SL ${p.stop_loss} · TP ${p.take_profit} · stop distance ${p.stop_distance.toFixed(2)} · ATR14 ${p.atr.toFixed(2)}\nEstimated gross stop loss at broker minimum ${p.broker_minimum_volume} lots: ${p.estimated_stop_loss_at_minimum_volume??'UNKNOWN'} ${p.account_currency} · ${p.minimum_volume_within_niblit_cap?'within lot cap':'ABOVE NIBLIT LOT CAP'}`;}).join('\n')}\nFees/slippage are not assumed zero. Unaffordable stops reject entry; stops are not squeezed or widened after review.`:
  'CRYPTO PROTECTION PREVIEW UNAVAILABLE · Crypto entries require ATR protection; other symbols use the existing MT5 protective-stop policy.';
 }catch(e){disable();el('exness-execution-state').textContent='CORE DEMO EXECUTION BLOCKED · Core or gateway unavailable';el('exness-status').textContent=e.message+' · demo execution blocked';el('exness-market').textContent='CURRENT MARKET DATA UNAVAILABLE · Last readback '+(last?new Date(last.checked_at*1000).toLocaleString():'never');}finally{busy=false;}}
el('exness-observe').onclick=async()=>{try{await call('sessions/observe',scope());await refresh();}catch(e){el('exness-review').textContent=e.message;}};
el('exness-propose').onclick=async()=>{try{const generation=reviewGeneration;const reviewed=await call('sessions/propose',scope());if(generation!==reviewGeneration)return;proposal=reviewed;el('exness-review').textContent=JSON.stringify(proposal.spec,null,2);el('exness-activate').disabled=false;}catch(e){proposal=null;el('exness-activate').disabled=true;el('exness-review').textContent=e.message;}};
el('exness-activate').onclick=async()=>{if(!proposal||!confirm(`Activate this reviewed Exness DEMO session? Maximum ${proposal.spec.limits.max_entries} entries, one open position at a time, ${proposal.spec.limits.max_volume} lots maximum each; broker stops remain after expiry.`))return;
 try{await call('sessions/activate',{id:proposal.id,spec_hash:proposal.spec_hash,acknowledgement:'ACTIVATE_BOUNDED_DEMO_SESSION',clear_emergency_stop:false});proposal=null;el('exness-activate').disabled=true;await refresh();}catch(e){el('exness-review').textContent=e.message;}};
el('exness-stop').onclick=async()=>{try{
 const latest=await call('sessions');nonce=latest.operator_nonce;
 const scopes=latest.sessions.filter(s=>s.spec.adapter==='exness_demo'&&['active','risk_halted','pending'].includes(s.state));
 for(const s of scopes)await call('sessions/stop',{id:s.id,emergency:false});
 proposal=null;el('exness-activate').disabled=true;await refresh();
 }catch(e){el('exness-review').textContent=e.message;}};
function invalidateReview(){reviewGeneration++;proposal=null;el('exness-activate').disabled=true;el('exness-review').textContent='Session settings changed. Review a fresh demo scope before activation.';}
for(const id of ['exness-minutes','exness-entries','exness-volume','exness-risk-cash','exness-risk-percent','exness-margin-percent','exness-positions']){el(id).onchange=invalidateReview;el(id).oninput=invalidateReview;}
el('exness-wave-15').onclick=()=>{el('exness-minutes').value='15';invalidateReview();};
el('exness-symbol').onchange=()=>{invalidateReview();void refresh();};
window.addEventListener('niblit:broker-view-changed',()=>{reviewGeneration++;proposal=null;el('exness-activate').disabled=true;el('exness-review').textContent='Account view changed. Review a fresh demo scope before activation.';});
setInterval(()=>{if(!document.hidden)void refresh();},15000);
setInterval(()=>{if(last&&Date.now()/1000-last.checked_at>30){el('exness-status').textContent='EXNESS DEMO STALE · Current account balance and execution readiness unavailable';el('exness-market').textContent='STALE MARKET DATA · Last readback '+new Date(last.checked_at*1000).toLocaleString();el('exness-inventory').textContent='CURRENT DEMO INVENTORY UNAVAILABLE';el('exness-execution-state').textContent='CORE DEMO EXECUTION BLOCKED · stale readback';disable();}},1000);
void refresh();})();
