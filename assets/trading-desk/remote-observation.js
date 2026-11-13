(function(root){
'use strict';
const byId=id=>document.getElementById(id);
const stamp=v=>typeof v==='number'?new Date(v*1000).toLocaleString():'UNKNOWN';
const value=v=>v===null||v===undefined?'UNKNOWN':String(v);
let lastRemote=null;
function render(remote){
 lastRemote=remote;
 let o=remote?.broker_observation;
 const panel=byId('remote-gateway-status');
 if(!panel)return;
 if(document.body.hasAttribute('data-remote-observation')){
   if(document.body.dataset.brokerView!=='exness')byId('mode').textContent='VPS XM · READ ONLY';
   byId('core-session-state').textContent='Real-money execution disabled. Reconciliation breaker remains governed by the VPS.';
 }
 if(o?.freshness==='fresh' && (typeof o.observation_at!=='number' || !Number.isFinite(o.observation_at) || Date.now()/1000-o.observation_at>=30 || Date.now()/1000<o.observation_at)){
   const previous={...o.balances,account:o.account,observed_at:o.observation_at,breaker:remote.breaker};
   o={...o,freshness:'stale',broker_authenticated:null,inventory_fresh:false,
     gateway:{...o.gateway,status:'stale',ssh_peer_verified:null},account:null,
     balances:Object.fromEntries(Object.keys(o.balances).map(k=>[k,null])),
     reconciliation:{status:'UNKNOWN',complete:false},emergency_stop_active:null,
     execution_permitted:false,last_verified:previous,
     warnings:[...o.warnings,'Broker observation expired locally'],
     execution_disabled_reasons:[...o.execution_disabled_reasons,'Observation exceeded 30 seconds']};
   remote={...remote,breaker:null};
 }
 if(!o){panel.textContent='Remote broker observation unavailable · REAL-MONEY EXECUTION DISABLED';return;}
 panel.textContent=[o.gateway.status.toUpperCase().replaceAll('_',' '),
   o.broker_authenticated?'XM BROKER VERIFIED':'XM BROKER UNVERIFIED',
   'Inventory '+o.freshness.toUpperCase(),'REAL-MONEY EXECUTION DISABLED'].join(' · ');
 const account=byId('remote-account-fields'), safety=byId('remote-safety-fields'), inventory=byId('remote-inventory-fields');
 account.textContent=o.freshness==='fresh'?
   ['Broker: '+value(o.account?.broker),'Login: '+value(o.account?.login),'Server: '+value(o.account?.server),
    'Environment: '+value(o.account?.environment),'Currency: '+value(o.account?.currency),
    ...Object.entries(o.balances).map(([k,v])=>k.replaceAll('_',' ')+': '+value(v)),
    'Broker observation: '+stamp(o.observation_at),'Core receipt: '+stamp(o.received_at)].join('\n'):
   'Current account values: UNAVAILABLE\nLast verified observation: '+stamp(o.last_verified?.observed_at)+
   (o.last_verified?'\nHistorical equity (not current): '+value(o.last_verified.equity):'');
 safety.textContent=['Gateway '+value(o.gateway.version)+' · identity '+value(o.gateway.identity),
   'SSH forward owner verified: '+value(o.gateway.ssh_peer_verified),
   'Gateway uptime (seconds): '+value(o.gateway.health?.uptime_seconds),
   'Gateway starts: '+value(o.gateway.health?.restart_count),
   'API latency (ms): '+value(o.gateway.latency_ms),
   'Canonical journal recorded: '+value(remote.canonical_journal?.recorded),
   'Terminal identity: '+value(o.account?.terminal_id),'Core synchronization: '+stamp(o.core_synchronized_at),
   'Observation freshness: '+o.freshness,'Reconciliation: '+value(o.reconciliation?.status),
   'Execution breaker: '+value(remote.breaker)+(remote.breaker?'':(' · last verified '+value(o.last_verified?.breaker))),'Emergency stop: '+value(o.emergency_stop_active),
   'Execution permitted: NO',...o.execution_disabled_reasons,...o.warnings].join('\n');
 inventory.textContent=o.inventory_fresh?[
   'Open positions: '+o.positions.length,JSON.stringify(o.positions,null,2),
   'Pending orders: '+o.pending_orders.length,JSON.stringify(o.pending_orders,null,2),
   'Recent orders (bounded history): '+JSON.stringify(o.history?.orders??null,null,2),
   'Recent deals (balance operations are not trading profits): '+JSON.stringify(o.history?.deals??null,null,2),
   'History checkpoint: '+stamp(o.history?.checkpoint),
   'History scope: '+value(o.reconciliation?.history_scope)].join('\n'):
   'Current positions, pending orders and history: UNAVAILABLE. Last recorded inventory is not current broker proof.';
}
root.renderRemoteObservation=render;
setInterval(()=>{
 const o=lastRemote?.broker_observation;
 if(o?.freshness==='fresh' && (typeof o.observation_at!=='number' || Date.now()/1000-o.observation_at>=30))render(lastRemote);
},1000);
})(window);
