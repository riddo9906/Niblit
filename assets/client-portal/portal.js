let csrf='', busy=false, workspace='shared',adminFocused=false;
let modelCheckAt=0,modelReady=false;
const adminPage=location.pathname==='/admin';
const el=id=>document.getElementById(id), status=text=>el('status').textContent=text;
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Please check the form fields');return data;}
function button(text,action){const b=document.createElement('button');b.textContent=text;b.onclick=async()=>{b.disabled=true;try{await action();await refresh();}catch(e){status(e.message);}finally{b.disabled=false;}};return b;}
async function refresh(){try{
const s=await api('/api/session?workspace='+encodeURIComponent(workspace));csrf=s.user.csrf;
el('login').hidden=true;el('registration').hidden=true;el('workspace').hidden=false;
if(adminPage&&(s.user.role!=='admin'||s.remote_client)){el('workspace').hidden=true;el('login').hidden=false;status('Administrator access required. Sign in with your approved owner account.');return;}
el('identity').textContent=`${s.user.name} · ${s.tier} · ${s.workspace_role}`;
el('workspace-picker').replaceChildren(...s.workspaces.map(w=>{const o=document.createElement('option');o.value=w.id;o.textContent=w.title;return o;}));el('workspace-picker').value=workspace;
el('privacy').textContent=workspace==='shared'?'Shared: all approved portal accounts can read this conversation.':'Private: workspace members can access this conversation. The server owner administers storage.';
el('chat').hidden=s.workspace_role==='viewer';if(Date.now()-modelCheckAt>20000){const model=await api('/api/model-status');modelCheckAt=Date.now();modelReady=model.ready;el('model-status').textContent=model.message+(model.model?' · '+model.model:'');}el('chat').querySelector('button').disabled=!modelReady;el('create-workspace').hidden=s.tier==='community';
el('messages').replaceChildren(...s.messages.map(m=>{const a=document.createElement('article'),h=document.createElement('h3'),p=document.createElement('p');h.textContent=`${m.name} · ${m.state}`;p.textContent=m.content;a.append(h,p);return a;}));
el('membership').hidden=s.workspace_role!=='owner';
if(s.workspace_role==='owner'){el('invite').hidden=s.tier!=='team';const members=await api('/api/workspaces/'+workspace+'/members');el('member-list').replaceChildren(...members.members.map(m=>{const p=document.createElement('p');p.textContent=`${m.name} · ${m.role} `;if(m.role!=='owner')p.append(button('Remove member',()=>api('/api/workspaces/'+workspace+'/members',{username:m.name,role:null})));return p;}));}
el('admin').hidden=(s.user.role!=='admin'||s.remote_client);el('tool-mode').hidden=(s.user.role!=='admin'||s.remote_client);el('tool-panel').hidden=(s.user.role!=='admin'||s.remote_client);el('learning-panel').hidden=(s.user.role!=='admin'||s.remote_client);if(s.user.role==='admin'&&!s.remote_client)await refreshTools();
if(s.user.role==='admin'&&!s.remote_client){if(adminPage&&!adminFocused){el('admin').scrollIntoView();adminFocused=true;}const a=await api('/api/admin');el('users').replaceChildren(...a.users.map(u=>{const p=document.createElement('p');p.textContent=`${u.name} · ${u.role} · ${u.signup_state==='pending'?'pending approval':u.active?'active':'revoked'} `;
if(u.signup_state==='pending')p.append(button('Approve as viewer',()=>api('/api/admin/approve/'+encodeURIComponent(u.name),{})));
if((u.active||u.signup_state==='pending')&&u.name!==s.user.name)p.append(button('Revoke access',()=>api('/api/admin/revoke/'+encodeURIComponent(u.name),{})));
const select=document.createElement('select');select.setAttribute('aria-label','Tier for '+u.name);for(const tier of ['community','personal','pro','team']){const o=document.createElement('option');o.value=tier;o.textContent=tier;select.append(o);}select.value=u.tier;p.append(select,button('Assign pilot tier',()=>api('/api/admin/plan/'+encodeURIComponent(u.name),{tier:select.value})));return p;}));el('audit').textContent=a.audit.map(x=>`${new Date(x.created*1000).toLocaleString()} ${x.name}: ${x.action}`).join('\n');}
}catch(e){status(e.message);if(e.message==='Workspace not found'){workspace='shared';el('messages').replaceChildren();return refresh();}if(e.message==='Please log in'){el('workspace').hidden=true;el('login').hidden=false;el('registration').hidden=adminPage;el('messages').replaceChildren();}}}
el('login').onsubmit=async e=>{e.preventDefault();try{const s=await api('/api/login',Object.fromEntries(new FormData(e.target)));csrf=s.csrf;e.target.reset();status('Connected.');await refresh();}catch(e){status(e.message);}};
el('chat').onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;const b=e.target.querySelector('button');b.disabled=true;el('workspace-picker').disabled=true;try{status('Niblit is answering…');await api('/api/messages',{...Object.fromEntries(new FormData(e.target)),workspace,use_tools:el('use-tools').checked});e.target.reset();status('Response received.');}catch(e){status(e.message);}finally{busy=false;b.disabled=false;el('workspace-picker').disabled=false;await refresh();}};
el('account').onsubmit=async e=>{e.preventDefault();try{await api('/api/admin/users',Object.fromEntries(new FormData(e.target)));e.target.reset();await refresh();status('Account created.');}catch(e){status(e.message);}};
el('logout').onclick=async()=>{try{await api('/api/logout',{});csrf='';workspace='shared';await refresh();}catch(e){status(e.message);}};
el('show-signup').onclick=()=>{el('signup').hidden=!el('signup').hidden;};
el('signup').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button'),d=Object.fromEntries(new FormData(e.target));if(d.password!==d.confirm){status('Passwords must match.');return;}b.disabled=true;try{const r=await api('/api/signup',{username:d.username,password:d.password,shared_workspace_acknowledged:d.acknowledged==='on'});e.target.reset();el('signup').hidden=true;status(r.message);}catch(e){status(e.message);}finally{b.disabled=false;}};
el('workspace-picker').onchange=async e=>{workspace=e.target.value;el('messages').replaceChildren();await refresh();};
el('create-workspace').onsubmit=async e=>{e.preventDefault();try{const w=await api('/api/workspaces',Object.fromEntries(new FormData(e.target)));workspace=w.id;e.target.reset();await refresh();status('Private workspace created.');}catch(e){status(e.message);}};
el('invite').onsubmit=async e=>{e.preventDefault();try{await api('/api/workspaces/'+workspace+'/members',Object.fromEntries(new FormData(e.target)));e.target.reset();await refresh();status('Member added.');}catch(e){status(e.message);}};
if(adminPage){el('registration').hidden=true;status('Administrator sign in: use your approved owner account.');}
refresh();setInterval(()=>{if(!busy&&!el('workspace').hidden)refresh();},5000);

async function refreshTools(){
try{const data=await api('/api/tool-activity?workspace='+encodeURIComponent(workspace));
el('tool-activity').textContent=data.events.map(e=>`${new Date(e.created*1000).toLocaleString()} · turn ${e.turn_id} · ${e.tool} · ${e.state}\nArguments: ${e.arguments}\nObservation: ${e.result}`).join('\n\n')||'No tool actions yet.';
el('proposals').replaceChildren(...data.proposals.map(p=>{const d=document.createElement('details'),s=document.createElement('summary'),body=document.createElement('pre');s.textContent=`#${p.id} ${p.title} · ${p.state}`;body.textContent=`Why: ${p.rationale}\n\nDraft:\n${p.patch}\n\nProposed validation (not executed):\n${p.validation}`;d.append(s,body);return d;}));
}catch(e){if(busy)status(e.message);}}
setInterval(()=>{if(!el('tool-panel').hidden)refreshTools();},2000);

async function refreshLearning(){try{const d=await api('/api/learning');el('learning-state').textContent=`${d.enabled?'Local study available':'Local study disabled'} · ${d.state} · ${d.completed} cycles · ${d.reason}`;el('learning-start').disabled=!d.enabled||d.state!=='stopped';el('learning-cycles').replaceChildren(...d.cycles.map(c=>{const box=document.createElement('details'),heading=document.createElement('summary'),body=document.createElement('pre');heading.textContent=`${c.category}: ${c.question} · ${c.state}`;body.textContent=`Evidence: ${c.evidence}\n\nLocal answer: ${c.answer}\n\nAssessment: ${c.assessment}`;box.append(heading,body);return box;}));}catch(e){status(e.message);}}
el('learning-start').onclick=async()=>{try{await api('/api/learning/start',{});await refreshLearning();}catch(e){status(e.message);}};
el('learning-stop').onclick=async()=>{try{await api('/api/learning/stop',{});await refreshLearning();}catch(e){status(e.message);}};
setInterval(()=>{if(!el('learning-panel').hidden)refreshLearning();},5000);
