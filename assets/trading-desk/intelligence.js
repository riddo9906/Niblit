'use strict';
(() => {
  const el=id=>document.getElementById(id);
  let binding=null, busy=false, lastRead=null;
  const base=document.querySelector('meta[name="desk-base"]')?.content||'';
  function updateFreshness(){
    if(!lastRead)return;
    const stale=Date.now()/1000-lastRead.received_at>60;
    const state=stale?'Stale observation · refresh required':lastRead.fresh?'Quote freshness verified at read':'Freshness unverified/stale';
    el('intelligence-status').textContent=`${state} · last read ${new Date(lastRead.received_at*1000).toLocaleString()} · Core ${lastRead.core.state} · funded execution disabled`;
  }
  setInterval(updateFreshness,5000);
  let continuousBusy=false;
  async function continuousStatus(){
    if(continuousBusy||!el('continuous-status'))return;
    continuousBusy=true;
    try{
      const response=await fetch('/api/intelligence/continuous',{signal:AbortSignal.timeout(5000)});
      if(!response.ok)throw Error('Core observation status unavailable');
      const result=await response.json();
      el('continuous-status').textContent=(result.running?'Observation workers running':result.state||'Observation workers stopped')+' · execution disabled';
      el('continuous-report').textContent=JSON.stringify({sources:result.jobs||[],comparisons:result.comparisons||[]},null,2);
    }catch(error){
      el('continuous-status').textContent='Current source status unavailable · refresh pending · execution disabled';
      el('continuous-report').textContent='No current worker health response.';
    }finally{continuousBusy=false;}
  }
  continuousStatus();setInterval(continuousStatus,15000);
  async function read(path) {
    const response=await fetch((base.startsWith('/')?base:'')+path,{signal:AbortSignal.timeout(75000)});
    if(!response.ok)throw Error('Observation service returned '+response.status);
    return response.json();
  }
  el('intelligence-bind').onclick=async()=>{
    if(busy)return;
    binding=null;lastRead=null;el('intelligence-refresh').disabled=true;
    el('intelligence-report').textContent='';
    try {
      const result=await read('/api/intelligence/desktop-binding');
      if(!result.identity)throw Error(result.reason||'Desktop account unavailable');
      binding=result;
      el('intelligence-binding').textContent=`${result.broker} · ${result.login} · ${result.server} · ${result.environment}. Read-only binding; no account switch.`;
      el('intelligence-refresh').disabled=false;
    } catch(error){el('intelligence-binding').textContent=error.message;}
  };
  el('intelligence-refresh').onclick=async()=>{
    if(!binding||busy)return;
    busy=true;lastRead=null;el('intelligence-refresh').disabled=true;
    el('intelligence-status').textContent='Reading closed candles through Core…';
    try {
      const query=new URLSearchParams({symbol:el('intelligence-symbol').value.trim(),account_identity:binding.identity,terminal_id:binding.terminal_id});
      const result=await read('/api/intelligence/desktop?'+query);
      if(!result.connected){binding=null;throw Error(result.reason||'Desktop observation unavailable');}
      const inventory=await read('/api/intelligence/components?'+query);
      lastRead=result;updateFreshness();
      el('intelligence-report').textContent=JSON.stringify({indicators_and_patterns:result.evidence,
        six_strategy_consensus:result.strategy_comparison,cognitive_receipt:result.core,
        components:inventory,limitations:result.limitations},null,2);
    } catch(error){
      el('intelligence-status').textContent='Unavailable: '+error.message;
      el('intelligence-report').textContent='No current observation. Refresh after checking the terminal and Core.';
    } finally {busy=false;el('intelligence-refresh').disabled=!binding;}
  };
})();

(()=>{const output=document.getElementById('prediction-report');if(!output)return;let busy=false;async function poll(){if(busy)return;busy=true;try{const response=await fetch('/api/intelligence/predictions',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('Unavailable');const value=await response.json();output.textContent=JSON.stringify(value,null,2);}catch(error){output.textContent='Prediction status unavailable. No current forecasts verified.';}finally{busy=false;}}poll();setInterval(poll,15000);})();
