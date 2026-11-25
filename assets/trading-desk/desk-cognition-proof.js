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
