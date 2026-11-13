/* Account VIEW selector. All identity, freshness and authority come from Core. */
(()=>{'use strict';
const el=id=>document.getElementById(id),key='niblit.remote-broker-view/1';
let choice='auto',last=null,received=0;
try{const saved=localStorage.getItem(key);if(['auto','xm','exness'].includes(saved))choice=saved;}catch(_){}
const selector=el('broker-view');selector.value=choice;
function render(data){
 last=data;received=Date.now()/1000;
 const xm=data?.remote_gateway,exness=data?.remote_demo;
 const configured=Boolean(xm?.configured||exness?.configured);
 el('broker-selector').hidden=!configured;if(!configured)return;
 const xmReady=xm?.broker_verified===true,exnessReady=exness?.verified===true;
 const connected=xmReady&&!exnessReady?'xm':exnessReady&&!xmReady?'exness':null;
 const view=choice==='auto'?(connected||'xm'):choice;
 document.body.dataset.brokerView=view;
 const name=view==='xm'?'XM live · read-only':(exnessReady?exness.account.broker+' demo · strategy testing':'Remote MT5 demo · strategy testing');
 const verified=view==='xm'?xmReady:exnessReady;
 el('broker-workspace-title').textContent=name;
 el('mode').textContent=view==='xm'?'XM LIVE · READ ONLY':'MT5 DEMO · BOUNDED SESSIONS';
 const active=xmReady&&exnessReady?'Account transition: both recent observations exist; verify the current MT5 login.':
   connected==='xm'?'VPS terminal verified on XM · 362350183 · XMGlobal-MT5 12.':
   connected==='exness'?'VPS terminal verified on '+exness.account.broker+' demo · '+exness.account.login+' · '+exness.account.server+'.':
   'No current broker account is verified through Core.';
 const mismatch=(!verified||!connected)?' Selected view is not the currently verified account. Switch accounts manually in the VPS MT5 terminal, then wait for fresh verification.':'';
 el('broker-view-status').textContent=active+' Displaying '+name+'.'+mismatch;
 if(view==='xm'){
   el('core-session-state').textContent='XM LIVE · REAL-MONEY EXECUTION DISABLED · Observation only';
 }else{
   const running=(data.sessions||[]).find(s=>s.spec?.adapter==='exness_demo'&&s.state==='active'&&s.expires>Date.now()/1000);
   el('core-session-state').textContent=!exnessReady?'Remote demo unverified · execution blocked':
    running?'Remote demo · bounded session active until '+new Date(running.expires*1000).toLocaleTimeString()+' · funded execution disabled':
    'Remote demo · no active execution scope · review and activate a bounded demo session';
 }
}
selector.onchange=()=>{
 choice=selector.value;try{localStorage.setItem(key,choice);}catch(_){}
 window.dispatchEvent(new CustomEvent('niblit:broker-view-changed',{detail:{choice}}));
 if(last)render(last);
};
window.renderBrokerView=render;
setInterval(()=>{if(last&&Date.now()/1000-received>30){
 el('broker-view-status').textContent='Core broker readback is stale. The selected view does not establish a connected account or trading permission.';
}},1000);
})();
