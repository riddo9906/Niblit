const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
(async()=>{
 let clock=100000, timer;
 const nodes=Object.fromEntries(['intelligence-symbol','intelligence-bind','intelligence-binding','intelligence-refresh','intelligence-status','intelligence-report'].map(id=>[id,{value:'BTCUSDm',disabled:false,textContent:''}]));
 class Clock extends Date {static now(){return clock;}}
 const response={connected:true,fresh:true,received_at:100,core:{state:'analyzed_by_core'},evidence:{},strategy_comparison:{candidates:[]}};
 const context={Date:Clock,JSON,URLSearchParams,AbortSignal:{timeout:()=>null},
  document:{getElementById:id=>nodes[id],querySelector:()=>({content:'/market-desk'})},
  setInterval:(fn,ms)=>{assert.ok([5000,15000].includes(ms));if(ms===5000)timer=fn;},
  fetch:async url=>({ok:true,json:async()=>url.includes('desktop-binding')?{identity:'demo',terminal_id:'terminal',environment:'demo'}:url.includes('components')?{components:[]}:response})};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../assets/trading-desk/intelligence.js'),'utf8'),context);
 await nodes['intelligence-bind'].onclick();
 await nodes['intelligence-refresh'].onclick();
 assert.match(nodes['intelligence-status'].textContent,/verified at read/);
 clock=161000;timer();
 assert.match(nodes['intelligence-status'].textContent,/Stale observation/);
 assert.match(nodes['intelligence-status'].textContent,/funded execution disabled/);
 assert.equal(nodes['intelligence-refresh'].disabled,false);
 console.log('PASS: desktop observation expires without a network request or trading action');
})().catch(error=>{console.error(error);process.exitCode=1;});
