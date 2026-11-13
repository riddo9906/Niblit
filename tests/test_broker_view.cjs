const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function fixture(saved){
 let now=1000000,timer;const events=[],writes=[];
 const nodes=Object.fromEntries(['broker-view','broker-selector','broker-view-status','broker-workspace-title','mode','core-session-state'].map(id=>[id,{value:'',textContent:'',hidden:false}]));
 const body={dataset:{}};
 class Clock extends Date{static now(){return now;}}
 const ctx={window:{dispatchEvent:e=>events.push(e)},document:{getElementById:id=>nodes[id],body},
 localStorage:{getItem:()=>saved,setItem:(...args)=>writes.push(args)},Date:Clock,
 CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
 setInterval:fn=>{timer=fn;},fetch:()=>{throw Error('Account view must not send broker commands');}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../assets/trading-desk/broker-view.js'),'utf8'),ctx);
 return {nodes,body,events,writes,render:ctx.window.renderBrokerView,
  select:value=>{nodes['broker-view'].value=value;nodes['broker-view'].onchange();},
  expire:()=>{now+=31000;timer();}};
}
function state(xm,demo){return {remote_gateway:{configured:true,broker_verified:xm},remote_demo:{configured:true,verified:demo,
 account:{login:'100000002',server:'Exness-MT5Trial10'}},sessions:[]};}
test('automatic view follows verified XM without demo authority',()=>{
 const f=fixture();f.render(state(true,false));assert.equal(f.body.dataset.brokerView,'xm');
 assert.match(f.nodes['core-session-state'].textContent,/REAL-MONEY EXECUTION DISABLED/);
 assert.match(f.nodes['broker-view-status'].textContent,/100000001/);assert.equal(f.events.length,0);
});
test('automatic view follows a manually connected Exness demo',()=>{
 const f=fixture();f.render(state(false,true));assert.equal(f.body.dataset.brokerView,'exness');
 assert.match(f.nodes['core-session-state'].textContent,/no active execution scope/);
});
test('selecting Exness while XM is connected remains unverified and grants nothing',()=>{
 const f=fixture();const data=state(true,false);f.render(data);f.select('exness');
 assert.equal(f.body.dataset.brokerView,'exness');
 assert.match(f.nodes['broker-view-status'].textContent,/Switch accounts manually/);
 assert.match(f.nodes['core-session-state'].textContent,/execution blocked/);
 assert.equal(data.remote_demo.verified,false);assert.equal(data.sessions.length,0);
 assert.equal(f.events[0].type,'niblit:broker-view-changed');
});
test('manual XM selection persists across fresh Exness observations',()=>{
 const f=fixture('xm');f.render(state(false,true));assert.equal(f.body.dataset.brokerView,'xm');
 assert.match(f.nodes['broker-view-status'].textContent,/Exness demo/);
 f.select('auto');assert.equal(f.body.dataset.brokerView,'exness');
});
test('conflicting recent proofs are reported as transition rather than authority',()=>{
 const f=fixture();f.render(state(true,true));assert.match(f.nodes['broker-view-status'].textContent,/Account transition/);
});
test('stale Core readback is not represented as a fresh connected account',()=>{
 const f=fixture();f.render(state(true,false));f.expire();assert.match(f.nodes['broker-view-status'].textContent,/stale/);
});
