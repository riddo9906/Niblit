'use strict';
// Extend the original SVG charts. Generated groups never own manual drawings.
(() => {
  const NS='http://www.w3.org/2000/svg', states=new Map(), filters=new Map();
  const el=(tag,attrs={},text=null)=>{const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==null)n.textContent=text;return n;};
  function render(svg,candles,bundle={annotations:[]},options={}) {
    const manual=svg.querySelector('[data-layer="manual"]');
    svg.querySelector('[data-layer="niblit-chart"]')?.remove();
    const root=el('g',{'data-layer':'niblit-chart'});svg.insertBefore(root,manual||null);svg.setAttribute('viewBox','0 0 1200 440');
    const rows=(candles||[]).filter(c=>['timestamp','open','high','low','close'].every(k=>typeof c[k]==='number'&&Number.isFinite(c[k])));
    if(!rows.length){root.append(el('text',{x:40,y:80,fill:'#cbd8e8'},'Completed candles unavailable'));return;}
    const interval=rows.length>1?rows.at(-1).timestamp-rows.at(-2).timestamp:300;const xmin=rows[0].timestamp,xmax=rows.at(-1).timestamp+2*interval;
    let low=Math.min(...rows.map(c=>c.low)),high=Math.max(...rows.map(c=>c.high));const pad=Math.max((high-low)*.08,high*.00005);low-=pad;high+=pad;
    const x=t=>100+(t-xmin)/(xmax-xmin)*890,y=p=>370-(p-low)/(high-low)*330;
    for(let i=0;i<5;i++){const price=low+(high-low)*i/4;root.append(el('line',{x1:100,x2:990,y1:y(price),y2:y(price),stroke:'#203248'}),el('text',{x:88,'text-anchor':'end',y:y(price)+4,fill:'#8ea4bc','font-size':12},price.toLocaleString(undefined,{maximumFractionDigits:5})));}
    const width=Math.max(2,Math.min(12,935/rows.length*.65));
    for(const c of rows){const color=c.close>=c.open?'#48ceb0':'#f38b9d';root.append(el('line',{x1:x(c.timestamp),x2:x(c.timestamp),y1:y(c.high),y2:y(c.low),stroke:color,'data-candle-time':c.timestamp}));root.append(el('rect',{x:x(c.timestamp)-width/2,y:Math.min(y(c.open),y(c.close)),width,height:Math.max(1,Math.abs(y(c.close)-y(c.open))),fill:color,'data-candle-body':c.timestamp}));}
    for(const index of [0,Math.floor(rows.length/2),rows.length-1]){const t=rows[index].timestamp;root.append(el('text',{x:x(t),y:400,fill:'#8ea4bc','font-size':12,'text-anchor':'middle'},new Date(t*1000).toISOString().slice(11,16)+' '+(options.timeBasis||'UTC')));}
    const stale=bundle.state==='stale'||bundle.expired||(bundle.expires_at&&Date.now()/1000>bundle.expires_at);const visible=(bundle.annotations||[]).filter(a=>(!options.strategies||options.strategies.has(a.strategy_id))&&(!options.position||a.position_ref===options.position||a.position_ref==null));
    let legend=0;
    const ids=new Set();
    for(const a of visible){
      const key=options.history?a.id+':'+a.revision:a.id;if(ids.has(key))continue;ids.add(key);
      const point=a.anchors?.[0];if(!point)continue;const color=a.style?.color||'#bed0e3';
      const group=el('g',{'data-annotation-id':a.id,'data-revision':a.revision,'data-price':point.price,'data-time':point.time,'data-strategy':a.strategy_id,'data-historical':Boolean(a.renderHistorical),'tabindex':0,'role':'img','aria-label':a.explanation,opacity:stale||a.renderHistorical?'.38':'1'});
      group.append(el('title',{},`${a.strategy_id} / ${a.role}\n${a.explanation}\n${a.basis}\nCoordinates: ${a.anchors.map(p=>p.price+' @ '+new Date(p.time*1000).toISOString()).join('; ')}\nSource ${a.source}; observed ${new Date(a.observed_at*1000).toISOString()}\n${a.invalidation||''}`));
      const dash=a.style?.dash?'5 4':'none';
      if(['level','entry','stop','target','invalidation'].includes(a.type)){
        if(y(point.price)>=35&&y(point.price)<=370)group.append(el('line',{x1:Math.max(52,x(point.time)),x2:990,y1:y(point.price),y2:y(point.price),stroke:color,'stroke-width':1.4,'stroke-dasharray':dash}));
      }else if(['zone','trendline','ray'].includes(a.type)&&a.anchors.length===2){
        const p=a.anchors[1];if(a.type==='zone')group.append(el('rect',{x:x(point.time),y:Math.min(y(point.price),y(p.price)),width:Math.max(4,x(p.time)-x(point.time)),height:Math.abs(y(p.price)-y(point.price)),stroke:color,fill:color,'fill-opacity':.10}));
        else group.append(el('line',{x1:x(point.time),y1:y(point.price),x2:x(p.time),y2:y(p.price),stroke:color,'stroke-dasharray':dash}));
      }else{
        group.append(el('circle',{cx:x(point.time),cy:y(point.price),r:a.renderHistorical?2.5:3,fill:color}));
      }
      if(!a.renderHistorical){
        const labelY=30+(legend++)*14,short={trend_v1:'TR',breakout_v1:'BRK',rsi_reversion_v1:'RSI',bollinger_reversion_v1:'BB',ema_pullback_v1:'EMA',squeeze_breakout_v1:'SQZ',position:'P'+(a.position_ref||'')};
        const price=Number(point.price).toLocaleString(undefined,{maximumFractionDigits:5}),outside=y(point.price)<35||y(point.price)>370;
        group.append(el('text',{x:1005,y:labelY,fill:color,'font-size':12},`${short[a.strategy_id]||a.strategy_id} ${a.assessment||a.signal||({open_rate:'entry',stop_loss_abs:'stop',thesis_initial_stop:'thesis stop',thesis_breakout_level:'thesis boundary',later_observation:'later market',missing_thesis:'no entry thesis'}[a.role]||a.role)} ${['signal','position','disagreement','exit','outcome','breakout'].includes(a.type)?'':price}${outside?' *':''}`));
      }
      group.addEventListener('mouseenter',()=>{group.querySelectorAll('line').forEach(n=>n.setAttribute('stroke-width','3'));});
      group.addEventListener('mouseleave',()=>{group.querySelectorAll('line').forEach(n=>n.setAttribute('stroke-width','1.4'));});
      const explain=()=>{const target=document.getElementById(svg.id+'-explanation');if(target)target.textContent=a.explanation+' Coordinates: '+a.anchors.map(p=>p.price+' @ '+new Date(p.time*1000).toISOString()).join('; ')+' Source: '+a.source+' · '+a.basis+' · '+a.id;};
      group.addEventListener('click',explain);group.addEventListener('focus',explain);root.append(group);
    }
    if(stale)root.append(el('text',{x:60,y:25,fill:'#ffc778','font-size':15},'STALE · historical evidence; current analytical abstention'));
    svg.setAttribute('aria-label',`${rows.length} real completed candles; ${visible.length} Niblit annotations; ${bundle.state||'awaiting evaluation'}`);
  }
  function controls(svg){
    const panel=document.createElement('div');panel.className='chart-controls';panel.id=svg.id+'-controls';
    const state=document.createElement('p');state.id=svg.id+'-annotation-state';state.setAttribute('role','status');
    const choices=document.createElement('div');choices.className='strategy-toggles';
    const positions=document.createElement('select');positions.setAttribute('aria-label','Filter chart position');positions.id=svg.id+'-position';positions.innerHTML='<option value="">All position references</option>';
    const timeframe=document.createElement('select');timeframe.setAttribute('aria-label','Chart timeframe');timeframe.innerHTML='<option value="5m">5m · six existing rules</option><option value="1m">1m · observation, rules abstain</option><option value="15m">15m · observation, rules abstain</option><option value="1h">1h · observation, rules abstain</option>';timeframe.id=svg.id+'-timeframe';
    const historical=document.createElement('button');historical.textContent='Show recent annotation history';historical.type='button';historical.setAttribute('aria-pressed','false');
    const exportLink=document.createElement('a');exportLink.textContent='Export Pine snapshot';exportLink.className='chart-export';
    const detail=document.createElement('p');detail.id=svg.id+'-explanation';detail.className='chart-explanation';detail.textContent='Select a drawing for evidence and exact coordinates. * marks a reference outside the candle price range.';
    panel.append(state,choices,positions,timeframe,historical,exportLink,detail);svg.after(panel);
    positions.onchange=()=>draw(svg.id);timeframe.onchange=()=>{const s=states.get(svg.id);if(s){s.generation++;s.data=null;s.candles=[];s.ui.state.textContent='Loading '+timeframe.value+' observations; existing M5 rules stay unchanged.';draw(svg.id);}void update(svg.id);};
    historical.onclick=async()=>{const s=states.get(svg.id);if(!s?.data?.annotations?.chart_key)return;try{const params=new URLSearchParams({environment:s.environment,symbol:s.symbol,timeframe:document.getElementById(svg.id+'-timeframe').value});const r=await fetch(((document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/')?document.querySelector('meta[name="desk-base"]').content:'')+'/api/charts/history?'+params);if(!r.ok)throw Error('History unavailable');const h=await r.json();s.history=(h.history||[]).flatMap(e=>e.changes.map(c=>c.annotation));s.showHistory=!s.showHistory;historical.textContent=s.showHistory?'Hide recent annotation history':'Show recent annotation history';historical.setAttribute('aria-pressed',String(s.showHistory));draw(svg.id);}catch(e){state.textContent+=' · '+e.message;}};
    return {state,choices,positions,exportLink};
  }
  function draw(id){const s=states.get(id);if(!s)return;const b=s.data?.annotations||{annotations:[]};const current=b.annotations||[];const annotationList=s.showHistory?[...current,...(s.history||[]).filter(a=>['signal','breakout','exit','outcome'].includes(a.type)&&a.anchors[0].time<(b.bar||0)).slice(0,48).map(a=>({...a,renderHistorical:true}))]:current;render(document.getElementById(id),s.candles,{...b,annotations:annotationList},{strategies:filters.get(id),position:s.ui.positions.value,history:s.showHistory,timeBasis:s.environment==='mt5'&&!s.data?.market?.time_mapping?.verified?'broker clock (unverified)':'UTC'});}
  async function update(id){const s=states.get(id);if(!s||s.busy||!s.symbol||s.feedAvailable===false)return;s.busy=true;const generation=s.generation;
    try{const params=new URLSearchParams({environment:s.environment,symbol:s.symbol,timeframe:document.getElementById(id+'-timeframe').value});const r=await fetch(((document.querySelector('meta[name="desk-base"]')?.content||'').startsWith('/')?document.querySelector('meta[name="desk-base"]').content:'')+'/api/charts/snapshot?'+params,{signal:AbortSignal.timeout(90000)});if(!r.ok)throw Error((await r.json()).detail||'Chart evaluation unavailable');const data=await r.json();if(states.get(id)!==s||generation!==s.generation)return;s.data=data;s.candles=data.market.candles;
      const b=data.annotations,names=[...new Set((b.annotations||[]).map(a=>a.strategy_id))];const prior=filters.get(id);filters.set(id,new Set(names.filter(name=>!s.names?.includes(name)||prior?.has(name))));s.names=names;s.ui.choices.replaceChildren();
      for(const name of names){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=filters.get(id).has(name);input.dataset.strategyToggle=name;input.onchange=()=>{input.checked?filters.get(id).add(name):filters.get(id).delete(name);draw(id);};label.append(input,document.createTextNode(name));s.ui.choices.append(label);}
      const selected=s.ui.positions.value;const refs=[...new Set((b.annotations||[]).map(a=>a.position_ref).filter(Boolean))];s.ui.positions.replaceChildren(new Option('All position references',''),...refs.map(v=>new Option('Position '+v,v)));if(refs.includes(selected))s.ui.positions.value=selected;
      s.ui.state.textContent=`${data.timeframe} · ${b.state} · ${b.regime||'unknown regime'} · ${b.consensus||'ABSTAIN'} · ${b.annotations?.length||0} evidence drawings · ${b.analysis_complete?'all registered rules assessed':'incomplete assessment'} · no order authority${data.position?' · position '+data.position.recorded.trade_id+' '+(b.annotations.find(a=>a.role==='assessment')?.assessment||'ABSTAIN')+' · saved M5 thesis '+data.position.entry_thesis?.state:''}`;
      s.ui.exportLink.href='/api/charts/pine?'+params;draw(id);
    }catch(e){s.ui.state.textContent='Chart analysis unavailable: '+e.message+' · other research and order controls are independent.';if(s.data){s.data.annotations={...s.data.annotations,state:'stale'};draw(id);}}finally{s.busy=false;}
  }
  function bind(id,candles,environment,symbol,binding){const svg=document.getElementById(id);let s=states.get(id);if(!s||s.symbol!==symbol||s.environment!==environment||s.binding!==binding){const ui=s?.ui||controls(svg);s={ui,environment,symbol,binding,candles,generation:(s?.generation||0)+1,data:null};states.set(id,s);filters.delete(id);}else if(document.getElementById(id+'-timeframe').value==='5m')s.candles=candles;s.feedAvailable=Boolean(candles?.length);const frame=document.getElementById(id+'-timeframe');for(const option of frame.options)option.disabled=environment==='mt5'&&option.value!=='5m';if(environment==='mt5')frame.value='5m';draw(id);void update(id);}
  globalThis.NiblitChart={render,bind,update,states};
})();
