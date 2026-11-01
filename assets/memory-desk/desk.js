const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="desk-token"]').content;
let currentStatus, offset=0, currentReview;
const titles={overview:'Memory, with evidence.',evidence:'Inspect what Niblit remembers.',documents:'Build a useful knowledge base.',containers:'The services behind memory.',niblit:'One connected Niblit runtime.'};
function node(tag, text='', className=''){const item=document.createElement(tag);item.textContent=text;if(className)item.className=className;return item;}
function notice(message,error=false){$('notice').hidden=!message;$('notice').textContent=message;$('notice').className=error?'error':'';}
async function api(path,body,method='POST',headers={}){
  const response=await fetch(path,body===undefined?{}:{method,headers:{'Content-Type':'application/json','X-Niblit-Desk-Token':token,...headers},body:body instanceof ArrayBuffer?body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.error||data.detail||'The action could not be completed');return data;
}
async function action(button,job){button.disabled=true;try{await job();}catch(error){notice(error.message,true);}finally{button.disabled=false;}}
function row(label,value){const item=node('div','','kv');item.append(node('span',label),node('strong',String(value??'Not reported')));return item;}
function metric(label,value,detail,good){const box=node('article','','metric');box.append(node('p',label),node('strong',value,good?'good':''),node('small',detail));return box;}
function renderStatus(s){
  currentStatus=s;
  const active=(s.memory.counts||[]).filter(x=>x.active).reduce((a,x)=>a+x.count,0);
  const queued=(s.memory.queue||[]).filter(x=>['pending','processing'].includes(x.state)).reduce((a,x)=>a+x.count,0);
  const complete=(s.memory.queue||[]).filter(x=>x.state==='complete').reduce((a,x)=>a+x.count,0);
  const worker=Boolean(s.core.available&&s.core.data.worker_running);
  $('metrics').replaceChildren(metric('Niblit Core',s.core.available?'Connected':'Unavailable',worker?'Memory worker active':'Memory worker not confirmed',s.core.available),
    metric('Qdrant',s.qdrant.available?'Connected':'Unavailable',s.qdrant.available?`v${s.qdrant.version} · ${s.qdrant.collections} collections`:'Check the container',s.qdrant.available),
    metric('Indexed passages',active.toLocaleString(),'Available to evidence retrieval',false),metric('Queued sources',queued.toLocaleString(),'Durably saved, awaiting projection',false));
  $('queue-label').textContent=`${complete.toLocaleString()} source jobs completed · ${queued.toLocaleString()} pending or processing`;
  $('import-progress').value=complete+queued?100*complete/(complete+queued):0;
  $('trading-summary').replaceChildren(row('Freqtrade',s.freqtrade.available?(s.freqtrade.dry_run?'Dry-run · simulated orders':'LIVE MODE — review configuration'):'API unavailable'),
    row('Freqtrade exchange',s.freqtrade.available?s.freqtrade.exchange:'Not verified'),
    row('Lean runtime',s.lean.available?`${s.lean.data.backend} · ${s.lean.data.market_data?.provider||'unknown data'}`:'Unavailable'));
  $('checked').textContent=`Checked ${new Date(s.checked_at).toLocaleString()} · ${s.memory.embedding_model}`;
  $('container-list').replaceChildren(...s.containers.map(container=>{
    const panel=node('article','','panel container');const title=node('h2',container.alias==='qdrant'?'Qdrant memory':'Freqtrade');title.append(node('span',container.running?'RUNNING':container.status,'badge '+(container.running?'verified':'')));
    panel.append(title,node('p',container.name,'image'),row('Image',container.image),row('Container',container.id),row('CPU',container.resources?.cpu),row('Memory',container.resources?.memory),row('Restarts',container.restart_count),row('Storage mounts',container.volumes?.length??0));
    if(container.alias==='freqtrade')panel.append(node('p','Start and restart are available only while dry-run remains enabled.','muted'));
    else panel.append(node('p','Restarting pauses semantic retrieval briefly. The volume and original evidence remain intact.','muted'));
    const controls=node('div','','actions');
    for(const verb of ['start','restart','stop']){const button=node('button',verb[0].toUpperCase()+verb.slice(1),'outline');button.addEventListener('click',()=>action(button,async()=>{
      if(verb!=='start'&&!confirm(`${verb==='stop'?'Stop':'Restart'} ${container.name}? Existing data volumes will be preserved.`))return;
      await api(`/api/containers/${container.alias}`,{action:verb});notice(`${container.name}: ${verb} requested. Refreshing actual service state…`);await refresh();}));controls.append(button);}
    panel.append(controls);if(container.alias==='qdrant'){const link=node('a','Open Qdrant dashboard ↗','button outline');link.href='http://127.0.0.1:6333/dashboard';link.target='_blank';link.rel='noreferrer';controls.append(link);}return panel;
  }));
}
async function refresh(){try{renderStatus(await api('/api/status'));}catch(error){notice(`Status unavailable: ${error.message}`,true);}}
function renderHit(record,reviewable=false){
  const item=node('article');const state=record.verification||'unverified';const badges=node('div');badges.append(node('span',state,'badge '+state),node('span',`Source confidence ${Math.round((record.confidence??.5)*100)}%`,'badge'));if(record.category)badges.append(node('span',record.category,'badge'));
  item.append(badges,node('p',record.content),node('small',record.citation||record.source_location||'Source not reported','citation'));
  if(record.provenance?.topic)item.append(node('small',`Topic: ${record.provenance.topic}`));
  if(record.provenance){const details=node('details');details.append(node('summary','Inspect source details'),node('pre',JSON.stringify({source_location:record.source_location||record.citation,provenance:record.provenance,observed_at:record.observed_at,embedding_model:record.embedding_model},null,2)));item.append(details);}
  if(reviewable){const button=node('button','Review evidence','outline review');button.addEventListener('click',()=>{
    currentReview=record.memory_id||record.id;$('review-content').textContent=record.content;$('review-confidence').value=record.confidence??.5;$('review-evidence').value='';$('source-checked').checked=false;$('review-dialog').showModal();});item.append(button);}
  return item;
}
async function browse(){const query=new URLSearchParams({query:$('browse-query').value,verification:$('verification').value,offset:String(offset),limit:'20'});const data=await api('/api/records?'+query);$('record-list').replaceChildren(...data.records.map(r=>renderHit(r,true)));$('record-count').textContent=`${data.total.toLocaleString()} matching passages · showing ${data.total?offset+1:0}–${Math.min(offset+20,data.total)}`;$('previous').disabled=offset===0;$('next').disabled=offset+20>=data.total;}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===button));document.querySelectorAll('.tab').forEach(s=>s.classList.toggle('active',s.id===button.dataset.tab));$('page-title').textContent=titles[button.dataset.tab];notice('');
  if(button.dataset.tab==='evidence')browse().catch(error=>notice(error.message,true));if(button.dataset.tab==='niblit'&&!$('niblit-frame').src)$('niblit-frame').src=$('niblit-frame').dataset.src;
}));
$('refresh').addEventListener('click',()=>action($('refresh'),refresh));
$('quick-search').addEventListener('submit',event=>{event.preventDefault();const button=event.target.querySelector('button');action(button,async()=>{const data=await api('/api/search',{query:$('quick-query').value,limit:6});$('quick-results').replaceChildren(...data.results.map(r=>renderHit(r)));if(!data.results.length)$('quick-results').append(node('p','No matching evidence found.'));notice(data.mode==='hybrid'?'Semantic and text search completed.':'Text search completed; semantic retrieval is degraded.');});});
$('browse-form').addEventListener('submit',event=>{event.preventDefault();offset=0;browse().catch(error=>notice(error.message,true));});
$('previous').addEventListener('click',()=>{offset=Math.max(0,offset-20);browse().catch(error=>notice(error.message,true));});$('next').addEventListener('click',()=>{offset+=20;browse().catch(error=>notice(error.message,true));});
$('retry').addEventListener('click',()=>action($('retry'),async()=>{const result=await api('/api/retry',{});notice(`${result.ready_for_retry} pending jobs are ready for the Core worker to retry.`);await refresh();}));
$('backup').addEventListener('click',()=>action($('backup'),async()=>{const result=await api('/api/backup',{});notice(`Consistent memory backup saved: ${result.path}`);}));
$('duplicates').addEventListener('click',()=>action($('duplicates'),async()=>{const result=await api('/api/consolidate',{});notice(`Scanned ${result.scanned} records and produced ${result.proposals.length} review candidates. Original evidence was not changed.`);}));
$('upload-form').addEventListener('submit',event=>{event.preventDefault();action($('upload-button'),async()=>{
  const file=$('document-file').files[0];if(!file)throw new Error('Choose a document first.');if(file.size>50000000)throw new Error('The maximum document size is 50 MB.');
  $('upload-result').textContent='Extracting readable text and saving source evidence…';const result=await api('/api/documents?filename='+encodeURIComponent(file.name),await file.arrayBuffer(),'POST',{'Content-Type':'application/octet-stream'});
  $('upload-result').textContent=`${result.name}: ${result.pages} pages parsed, ${result.queued} passages queued. ${result.truncated?'Parser coverage limit reached; this is a partial import.':'The parsed text is saved in the queue.'} Claims remain unverified.`;await refresh();});});
$('review-form').addEventListener('submit',event=>{event.preventDefault();const button=event.target.querySelector('button');action(button,async()=>{await api(`/api/records/${encodeURIComponent(currentReview)}/review`,{verification:$('review-decision').value,confidence:Number($('review-confidence').value),evidence:$('review-evidence').value,source_checked:$('source-checked').checked});$('review-dialog').close();notice('Operator decision saved with its evidence and audit record.');await browse();await refresh();});});
$('cancel-review').addEventListener('click',()=>$('review-dialog').close());
$('load-logs').addEventListener('click',()=>action($('load-logs'),async()=>{const data=await api(`/api/containers/${$('log-service').value}/logs`);$('logs').textContent=data.logs||'No recent stdout activity reported.';}));
refresh();setInterval(refresh,15000);
