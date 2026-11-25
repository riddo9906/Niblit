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
   if(!node||raw===lastReview)return;
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
