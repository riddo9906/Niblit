const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
function fixture(){
 let now=1001000, timer;
 const nodes=Object.fromEntries(['remote-gateway-status','remote-account-fields','remote-safety-fields','remote-inventory-fields'].map(k=>[k,{textContent:''}]));
 class Clock extends Date{static now(){return now;}}
 const context={window:{},document:{body:{hasAttribute:()=>false},getElementById:id=>nodes[id]},Date:Clock,setInterval:fn=>{timer=fn;}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../assets/trading-desk/remote-observation.js'),'utf8'),context);
 const remote={breaker:'RECONCILIATION_REQUIRED',canonical_journal:{recorded:true},broker_observation:{
 gateway:{status:'read_only_operational',version:'0.2.2',health:{},ssh_peer_verified:true},
 account:{broker:'XM double',login:'362350183',server:'XMGlobal-MT5 12',environment:'live',currency:'USD'},
 balances:{balance:21.03,equity:21.03,margin:0,free_margin:21.03},observation_at:1000,received_at:1001,core_synchronized_at:1001,
 freshness:'fresh',broker_authenticated:true,inventory_fresh:true,positions:[],pending_orders:[],history:{orders:[],deals:[],checkpoint:1000},
 reconciliation:{status:'REVIEW_REQUIRED',complete:false},execution_disabled_reasons:['funded_execution_disabled'],warnings:[]}};
 return {nodes,remote,render:context.window.renderRemoteObservation,expire:()=>{now=1031000;timer();}};
}
test('latched breaker does not hide verified read-only account',()=>{
 const f=fixture();f.render(f.remote);
 assert.match(f.nodes['remote-account-fields'].textContent,/balance: 21.03/);
 assert.match(f.nodes['remote-safety-fields'].textContent,/RECONCILIATION_REQUIRED/);
 assert.match(f.nodes['remote-safety-fields'].textContent,/Execution permitted: NO/);
});
test('non-empty simulated inventory is rendered with stable identifiers',()=>{
 const f=fixture();f.remote.broker_observation.positions=[{ticket:123,volume:'0.01'}];f.remote.broker_observation.pending_orders=[{ticket:456}];f.render(f.remote);
 assert.match(f.nodes['remote-inventory-fields'].textContent,/Open positions: 1/);
 assert.match(f.nodes['remote-inventory-fields'].textContent,/"ticket": 123/);
 assert.match(f.nodes['remote-inventory-fields'].textContent,/Pending orders: 1/);
});
test('local expiry removes current values even if Core request hangs',()=>{
 const f=fixture();f.render(f.remote);f.expire();
 assert.match(f.nodes['remote-account-fields'].textContent,/Current account values: UNAVAILABLE/);
 assert.doesNotMatch(f.nodes['remote-account-fields'].textContent,/balance: 21.03/);
 assert.match(f.nodes['remote-account-fields'].textContent,/Historical equity \(not current\): 21.03/);
 assert.match(f.nodes['remote-gateway-status'].textContent,/Inventory STALE/);
 assert.match(f.nodes['remote-safety-fields'].textContent,/last verified RECONCILIATION_REQUIRED/);
});
