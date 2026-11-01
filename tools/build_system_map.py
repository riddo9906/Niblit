"""Render the reviewed delivery matrix as a private, offline interactive map."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    text=(ROOT/'docs/NIBLIT_MASTER_PLAN.md').read_text(encoding='utf-8')
    matrix=text.split('## Current delivery matrix',1)[1].split('## Next implementation batch',1)[0]
    nodes=[]
    for line in matrix.splitlines():
        cells=[c.strip() for c in line.split('|')[1:-1]]
        if len(cells)!=3 or cells[0]=='User goal' or cells[0].startswith('---'):
            continue
        title,status,evidence=cells
        lower=title.lower()
        group='Runtime and tools'
        if any(w in lower for w in ['memory','qdrant','pdf','file understanding']):group='Memory and knowledge'
        elif any(w in lower for w in ['trading','mt5','freqtrade','finance','market','signals']):group='Markets and finance'
        elif any(w in lower for w in ['autonomy','growth','steward','pip','ruflo','expertise']):group='Learning and agents'
        elif any(w in lower for w in ['website','domain','business','installer','executable','fresh','explain all']):group='Product and delivery'
        elif any(w in lower for w in ['hosted','sign-up','private','cloud container']):group='Hosted clients'
        elif any(w in lower for w in ['cctv','faces','eyes']):group='Vision roadmap'
        nodes.append({'title':title,'status':status,'evidence':evidence,'group':group})
    data=json.dumps(nodes).replace('</','<\\/')
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Niblit · System and delivery map</title>
<style>:root{color-scheme:dark;font:16px/1.6 system-ui;background:#101b18;color:#e6eee8}body{max-width:1240px;margin:auto;padding:28px}h1{font-size:clamp(30px,5vw,52px);line-height:1.1;letter-spacing:-2px}p{max-width:820px;color:#b8c9be}a{color:#c5ed92}header{border-bottom:1px solid #3d5747;padding-bottom:24px}.eyebrow{letter-spacing:2px;font-size:12px;color:#c5ed92}.root{text-align:center;margin:30px auto;width:fit-content;border:1px solid #6e8a74;border-radius:16px;padding:16px 30px;background:#20372a}.root small{display:block;color:#c5ed92}.layout{display:grid;grid-template-columns:2fr 1fr;gap:24px}.branches{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}.branch{border-top:2px solid #7e9b66;padding-top:12px}.branch h2{font-size:18px}.node{display:block;width:100%;text-align:left;padding:12px 15px;margin:9px 0;border:1px solid #3d5747;border-radius:9px;background:#192b22;color:inherit;font:inherit;cursor:pointer}.node:hover,.node[aria-pressed=true]{border-color:#c5ed92;background:#2c4430}.node span{display:block;color:#bdcfb8;font-size:12px}.detail{position:sticky;top:20px;align-self:start;background:#24382b;border-radius:14px;padding:24px}.detail h2{font-size:24px;line-height:1.3}.detail p{color:#e1e9df}.detail strong{color:#c5ed92}nav{display:flex;flex-wrap:wrap;gap:18px;margin-top:20px}.counts{padding:15px 0;font-size:14px}.note{font-size:13px}footer{border-top:1px solid #3d5747;margin-top:32px;padding-top:20px}@media(max-width:800px){.layout{grid-template-columns:1fr}.detail{position:static;grid-row:1}.branches{grid-template-columns:1fr}body{padding:20px}}</style>
<header><div class="eyebrow">ENGINEHEAD SOFTWARE DEVELOPMENT / PRIVATE DEVELOPMENT MAP</div><h1>Niblit: the whole picture.</h1><p>Source, requests, evidence and the work that connects them. Updated 29 October 2026. This map distinguishes working paths from plans; it does not declare the entire system complete.</p><nav><a href="../NIBLIT_MASTER_PLAN.md">Delivery plan</a><a href="../NIBLIT_HUMAN_GUIDE.md">What / how / why guide</a><a href="../request-audit/README.md">143-request register</a><a href="../code-atlas/README.md">Source atlas</a></nav></header>
<div class="root"><small>COMPANY</small><b>Enginehead Software Development</b><div>↓</div><small>PRODUCT</small><b>Niblit · intelligence runtime and toolbox</b></div><div class="counts" id="counts"></div><div class="layout"><main id="branches" class="branches"></main><aside id="detail" class="detail" aria-live="polite"><h2>Select a capability</h2><p>Open a node to see its current evidence and remaining work.</p><p class="note">A capability label or test count is not proof of expertise. Private workspaces isolate clients, not the host administrator.</p></aside></div><footer><p class="note">12 relevant conversations inventoried. Individual reconciliation remains in progress. No paid inference ran in this audit. This map contains local project context and is not part of the public marketing website.</p></footer>
<script>const nodes=__DATA__;const branches=document.getElementById('branches'),detail=document.getElementById('detail');document.getElementById('counts').textContent=nodes.length+' capability areas · source-backed status matrix · select any node';for(const group of [...new Set(nodes.map(n=>n.group))]){const section=document.createElement('section');section.className='branch';const h=document.createElement('h2');h.textContent=group;section.append(h);for(const n of nodes.filter(n=>n.group===group)){const b=document.createElement('button');b.className='node';b.setAttribute('aria-pressed','false');const title=document.createElement('b'),state=document.createElement('span');title.textContent=n.title;state.textContent=n.status;b.append(title,state);b.onclick=()=>{document.querySelectorAll('.node').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');const h=document.createElement('h2'),s=document.createElement('strong'),p=document.createElement('p');h.textContent=n.title;s.textContent=n.status;p.textContent=n.evidence;detail.replaceChildren(h,s,p);};section.append(b);}branches.append(section);}</script></html>'''.replace('__DATA__',data)
    out=ROOT/'docs/system-map';out.mkdir(exist_ok=True)
    (out/'index.html').write_text(html,encoding='utf-8')
    print(f'Rendered {len(nodes)} capability areas')


if __name__=='__main__':
    main()
