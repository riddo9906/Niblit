"""Triage retrieved request excerpts into an inspectable delivery register.

Mapping is conservative keyword-based indexing, not automatic proof of completion.
The reviewed master matrix remains authoritative for current feature conclusions.
"""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/request-audit'
RULES=[
 ('Identity matching','Excluded',r'passerby faces|matching.*social media', 'NIBLIT_MASTER_PLAN.md: excluded face-identification request'),
 ('Client workspaces','Partial',r'sign up|private option|tiers|external server|client.*interface|hosting.*vercel','CLIENT_PORTAL.md; tests/test_server_manager.py; tests/test_portal_workspaces.py'),
 ('Company website','Verified publication',r'enginehsd|website for niblit|public marketing','NIBLIT_MASTER_PLAN.md: company website version 2'),
 ('Fresh install and manager portability','Planned',r'path manager|new desktop|from scratch|all managers|manager update','DELIVERY_TRACKER_20261029.md'),
 ('Domain learning and autonomy','Partial',r'autonom|cognition|growing|grow.*intelligent|trading brain|coherent feedback','NIBLIT_MASTER_PLAN.md: autonomy and domain learning gaps'),
 ('Memory and Qdrant','Partial',r'qdrant|memory framework|memory system|knowledge ingestion|memory laboratory','modules/memory_laboratory; diagnostics/manual-ui-audit-20261029.md'),
 ('PDF and file understanding','Partial',r'pdf|file.understand|attached file|attachment','modules/chat_attachments.py; NIBLIT_PROGRESS.md: PDF and Phase 5X evidence'),
 ('Commands and toolbox','Partial',r'ctrl|command|toolbox|programmer','modules/command_surface_audit.py; diagnostics/manual-ui-audit-20261029.md'),
 ('Trading and market adapters','Partial',r'mt5|freqtrade|freqtade|trading|broker|binance|market|trade clos|submit order|algo trading','TRADING_DESK.md; MT5_DEMO_CONNECTION.md; diagnostics/mt5-demo-submission-acceptance.json'),
 ('Steward and model/tool bridge','Partial',r'steward|openai|astra|api key|api code|agent|inference|ruflo|navigate_and_describe','../niblit-steward/README.md; NIBLIT_MASTER_PLAN.md'),
 ('VS Code gateway','Historical',r'vscode|vs code|llm gateway|copilot','github-copilot-llm-gateway; historical gateway conversation'),
 ('Runtime and packaging','Partial',r'boot|backend|backened|build|tauri|rustup|lifecycle|readiness|phase 5','DESKTOP_RUNTIME_ARCHITECTURE.md; NIBLIT_PROGRESS.md'),
 ('Pip and desktop companion','Partial',r'pip|companion|pulse|desktop view|friend','../trade-signal-desk/README.md'),
 ('Vision and OS','Planned',r'cctv|camera|recognition|niblits eyes|os part','NIBLIT_MASTER_PLAN.md: later vision/OS milestone'),
 ('Business development','Planned',r'make money|entrepreneur|entreneur|service|revenue','NIBLIT_MASTER_PLAN.md: business validation'),
]


def clean(text):
    text=re.sub(r'<[^>]+>','',text)
    return re.sub(r'\s+',' ',text).strip()


def main():
    path=OUT/'conversations.json';data=json.loads(path.read_text(encoding='utf-8'))
    for row in data['requests']:
        text=clean(row['excerpt'])
        row['category']='General direction / context'
        row['status']='Needs individual verification'
        row['review_status']='Triage only: compare the full request to source and acceptance evidence'
        row['evidence']=[]
        for category,status,pattern,evidence in RULES:
            if re.search(pattern,text,re.I):
                row.update(category=category,status=status,evidence=[evidence]);break
    path.write_text(json.dumps(data,indent=2),encoding='utf-8')
    md=['# Conversation-by-conversation request register','',
        '29 October 2026. Every retrieved user message has a row below. This is a',
        '**triage register**, not 143 independent completion certifications. Category',
        'statuses refer to the current capability area; exact request acceptance still',
        'needs individual reconciliation. Read the reviewed [master matrix](../NIBLIT_MASTER_PLAN.md)',
        'for evidence and limits. Full retrieved excerpts and turn IDs are in',
        '[conversations.json](conversations.json). UI snapshots and secrets are omitted.','',
        'Coverage: 12 relevant accessible conversations, 143 request messages. Unrelated',
        'personal conversations were excluded. Archived Codex inventory contained one',
        'unrelated voice thread. Missing attachments, screenshots and older unavailable',
        'content have not been reconstructed. Long excerpts are explicitly truncated.','',
        'The two longer relevant chats were paginated to their returned end. Other',
        'selected reads returned no additional page. This does not establish that all',
        'historical ChatGPT messages or attachment contents were available to the tool.','']
    for conv in data['coverage']:
        rows=[r for r in data['requests'] if r['thread_id']==conv['thread_id']]
        md += ['## '+clean(conv['title'])[:160],'',f"Thread: `{conv['thread_id']}`",'', '| Request | Excerpt | Area | Current area status |','|---|---|---|---|']
        for r in rows:
            excerpt=clean(r['excerpt']).replace('|','/')[:260]
            md.append(f"| {r['id']} | {excerpt} | {r['category']} | {r['status']} |")
        md.append('')
    md+=['## Reconciliation procedure','',
         'For each row: read the full request/attachment when available; split distinct',
         'acceptance conditions; link current source and an actual test/receipt; mark',
         'Historical, Partial, Planned, Verified or Excluded with a date. Keep prior',
         'evidence when a newer build regresses. Do not count a keyword match, stored',
         'fact or a generated explanation as verification.','']
    (OUT/'README.md').write_text('\n'.join(md),encoding='utf-8')
    print(f"Indexed {len(data['requests'])} requests from {len(data['coverage'])} conversations")


if __name__=='__main__':
    main()
