"""Bounded Chat admission adapter over the existing Core tool authority.

This is not an autonomous planner. Explicit objectives map to fixed registered
capabilities; learning writes require their existing operator permission.
Model text and memories never select a tool.
"""
import json
import re
import uuid
from datetime import datetime, timezone


def inference_snapshot():
    """Observe the configured authenticated gateway; never start a model."""
    from modules.portal_model import settings
    import httpx
    facts = {'controller': 'Niblit Core', 'provider': 'UNKNOWN',
             'available_models': [], 'endpoint': 'UNKNOWN',
             'fallback': False, 'generation_performed': False,
             'observed_at': datetime.now(timezone.utc).isoformat()}
    try:
        backend, endpoint, headers = settings()
        facts['endpoint'] = endpoint
        if backend != 'local_gguf':
            return {**facts, 'status': 'UNKNOWN', 'issue': 'unsupported_gateway'}
        with httpx.Client(trust_env=False, timeout=3) as client:
            response = client.get(endpoint + '/v1/models', headers=headers)
            response.raise_for_status()
            models = response.json().get('data', [])
        facts.update(status='observed', provider='llama.cpp', available_models=[
            str(m['id'])[:160] for m in models[:16] if isinstance(m.get('id'), str)])
    except Exception as exc:
        facts.update(status='UNKNOWN', issue=type(exc).__name__)
    return facts


def admission(text):
    """Conservative interpretation; ambiguous actions do not execute."""
    lower = text.casefold().strip()
    if lower in {'review demo execution preparation','review demo execution preparation.'}:
        return 'execution_rehearsal',[('recall_environment_preparation',{})]

    if lower.rstrip('.!') in ('run the governed execution rehearsal','run an intercepted execution rehearsal for mt5 and freqtrade'):
        return 'execution_rehearsal',[('run_execution_rehearsal',{})]
    if lower.rstrip('.!')=='explain the latest execution rehearsal':
        return 'execution_rehearsal',[('recall_execution_rehearsal',{})]
    condition_review=re.fullmatch(r'review (mt5|freqtrade) execution conditions[.!]?',lower)
    if condition_review:
        return 'trading_readiness',[('observe_trading',{'review':True,'platform':condition_review.group(1)})]
    if lower.rstrip('.!')=='compare current trading risk and costs':
        return 'trading_readiness',[('observe_trading',{'review':True,'platform':'all'})]
    if lower.rstrip('.!')=='explain why execution remains denied':
        return 'trading_readiness',[('recall_trading_observations',{'review':True})]
    if lower.rstrip('.!') in ('observe trading now','compare trading observations','recall trading observations'):
        return 'trading_readiness', [('observe_trading' if lower.startswith('observe ') else 'recall_trading_observations',{})]
    readiness=re.fullmatch(r'(?:explain|recall) reconciled (?:(mt5|freqtrade) )?trading (?:readiness|history)[.!]?',lower)
    if readiness:
        return 'trading_readiness',[('read_trading_readiness',{'platform':readiness.group(1) or 'all'})]
    paper = re.fullmatch(r'(?:please )?run a governed paper trading evaluation using the approved replay dataset(?: as (paper-[a-z0-9-]{8,48}))?(?:, evaluate strategy agreement, execute only eligible simulated trades, monitor positions, and report the outcome)?[.!]?',lower)
    if paper:
        return 'paper_replay',[('run_paper_replay',{'run_id':paper.group(1) or 'paper-'+uuid.uuid4().hex,
            'dataset':'governed_paper_v1'})]
    paper_read = re.fullmatch(r'(?:explain|recall|read) paper (?:episode|evaluation) (paper-[a-z0-9-]{8,48})[.!]?',lower)
    if paper_read:
        return 'paper_replay',[('read_paper_episode',{'run_id':paper_read.group(1)})]
    paper_cancel = re.fullmatch(r'cancel paper (?:episode|evaluation) (paper-[a-z0-9-]{8,48})[.!]?',lower)
    if paper_cancel:
        return 'paper_replay',[('cancel_paper_replay',{'run_id':paper_cancel.group(1)})]
    natural_research = re.fullmatch(r'(?:please )?research (.{3,500}?),? and learn (?:the )?(?:useful )?findings[.!]?',text.strip(),re.I)
    if natural_research:
        import hashlib
        objective=natural_research.group(1).rstrip(',')
        subject='research.'+hashlib.sha256(objective.casefold().encode()).hexdigest()[:16]
        return 'learning', [('run_learning', {
            'profile':'public_sources','objective':objective,'subject':subject,
            'permitted_actions':['recall','fetch_public','store_observations'],
            'sources':[{'kind':'public_search'}],
            'max_seconds':30,'max_research_calls':4,'max_accepted_records':4})]
    discovery = re.fullmatch(r'(?:please )?research (.{3,500}?) and learn (?:for|as) (?:subject )?([A-Za-z0-9_.-]{3,120})[.!]?',text.strip(),re.I)
    if discovery and ' using https://' not in text.lower():
        return 'learning', [('run_learning', {
            'profile':'public_sources','objective':discovery.group(1),
            'subject':discovery.group(2).rstrip('.'),
            'permitted_actions':['recall','fetch_public','store_observations'],
            'sources':[{'kind':'public_search'}],
            'max_seconds':30,'max_research_calls':4,'max_accepted_records':4})]
    research = re.fullmatch(r'(?:please )?research (.{3,500}?) using (https://\S+(?:\s*,\s*https://\S+)*) (?:and )?learn (?:for|as) (?:subject )?([A-Za-z0-9_.-]{3,120})[.!]?',text.strip(),re.I)
    if research:
        urls = [u.strip() for u in research.group(2).split(',')]
        return 'learning', [('run_learning', {
            'profile':'public_sources','objective':research.group(1),
            'subject':research.group(3).rstrip('.'),
            'permitted_actions':['recall','fetch_public','store_observations'],
            'sources':[{'kind':'public_web','url':u} for u in urls],
            'max_seconds':30,'max_research_calls':min(len(urls),4),'max_accepted_records':min(2*len(urls),8)})]
    learning = re.fullmatch(r'(?:please )?learn (?:fields? )?([A-Za-z_][A-Za-z0-9_, ]*) from (?:file |document )?[`\"]?([^`\"\s]+\.json)[`\"]? (?:for|as) (?:subject )?([A-Za-z0-9_.-]{3,120})(?: and explain what you discovered)?[.!]?', text.strip(), re.I)
    if learning:
        fields = [field.strip() for field in learning.group(1).split(',')]
        return 'learning', [('run_learning', {
            'objective':f"Learn {', '.join(fields)} declarations from {learning.group(2)}",
            'subject':learning.group(3).rstrip('.'),
            'permitted_actions':['recall','read_workspace','store_observations'],
            'sources':[{'kind':'workspace_json','path':learning.group(2),'fields':fields}],
            'max_seconds':30,'max_research_calls':1,'max_accepted_records':min(len(fields),8)})]
    if re.match(r'^(?:please )?learn\b', lower):
        return 'learning_clarification', []
    application = re.fullmatch(r'apply learned facts for ([A-Za-z0-9_.-]{3,120})\s*:\s*(.{3,2000})',text.strip(),re.I)
    if application:
        return 'learned_application', [('recall_learning', {'subject':application.group(1)})]
    recall = re.match(r'^(?:what did you learn about|recall learned facts for|use learned facts for)\s+([A-Za-z0-9_.-]{3,120})', text.strip(), re.I)
    if recall:
        return 'learned_recall', [('recall_learning', {'subject':recall.group(1).rstrip('.')})]
    if lower.rstrip('?.!') in {'who are you', 'what are you', 'identify yourself'}:
        return 'identity', []
    # Questions/discussion about doing something are not execution requests.
    if re.match(r'^(explain (?!file\b)|what (?:is|are|does)|how (?:does|would)|could .* explain)', lower):
        return 'retrieval', []
    if re.search(r'(which|what|no local|so not|are you|is this).{0,65}(model|qwen|niblit responding|backend)|is this niblit responding', lower):
        return 'identity', []
    if re.search(r'you (?:are not|aren.t|are\s+not really).{0,35}(say|claim|niblit|real)', lower):
        return 'identity_challenge', []
    if re.search(r'\b(?:perform|run|do|conduct)\b.{0,45}\bself[- ]assessment\b', lower):
        return 'diagnostic', [('runtime_status', {}), ('knowledge_stats', {})]
    if re.match(r'^(?:(?:please|can you|could you) )?(?:inspect|check|investigate) (?:the |your )?(?:runtime|service health|capabilities)', lower):
        return 'diagnostic', [('runtime_status', {}), ('knowledge_stats', {})]
    match = re.match(r'^(?:please )?(?:read|inspect|explain|understand) (?:the )?file\s+[`\"]?([^`\"\n]+?)[`\"]?\s*$', text, re.I)
    if match:
        return 'file', [('workspace_read', {'path': match.group(1).strip(), 'max_chars': 4000})]
    if re.match(r'^(?:please )?(?:research|search (?:the )?web (?:for|about))\s+', lower):
        query = re.sub(r'^(?:please )?(?:research|search (?:the )?web (?:for|about))\s+', '', text, flags=re.I)
        return 'research', [('web_search', {'query': query[:500]})]
    if re.match(r'^(?:please )?(?:execute|run|delete|write|edit|install|restart|activate|place|buy|sell|close|modify)\b', lower):
        return 'authorization_required', []
    return 'conversation', []


def execute_readonly(core, plan):
    from modules.core_tool_runtime import get_governed_tool_loop
    try:
        loop = get_governed_tool_loop(lambda: core)
    except Exception:
        loop = None
    allowed = {'runtime_status', 'knowledge_stats', 'workspace_read', 'web_search', 'run_learning', 'recall_learning',
               'run_paper_replay','read_paper_episode','cancel_paper_replay','read_trading_readiness','observe_trading','recall_trading_observations','run_execution_rehearsal','recall_execution_rehearsal','recall_environment_preparation'}
    receipts = []
    for name, arguments in plan[:2]:
        receipt = {'id': str(uuid.uuid4()), 'tool': name,
                   'observed_at': datetime.now(timezone.utc).isoformat()}
        if loop is None:
            outcome = {'status': 'error', 'error': 'tool_runtime_unavailable'}
        elif name not in allowed:
            outcome = {'status': 'rejected', 'error': 'outside_readonly_chat_scope'}
        else:
            try:
                outcome = loop.invoke(name, arguments)
            except Exception:
                outcome = {'status': 'error', 'error': 'tool_invocation_failed'}
        # Existing capabilities can return an error inside a successful dispatch.
        dispatch_status = outcome.get('status', 'error')
        result = outcome.get('result')
        if outcome.get('status') == 'success' and isinstance(result, dict) and result.get('error'):
            outcome = {**outcome, 'status': 'error', 'error': 'capability_reported_error'}
        if isinstance(result, dict) and str(result.get('status', '')).startswith(
                ('[niblit_exec error:', '[router_exec error:', '[niblit_exec: core not available')):
            outcome = {**outcome, 'status': 'error', 'error': 'core_status_unavailable'}
        receipt.update(status=outcome.get('status', 'error'), duration_ms=outcome.get('duration_ms', 0))
        receipt['arguments'] = arguments
        receipt['permission_decision'] = ('passed_or_not_required' if dispatch_status == 'success' else
                                          'denied' if dispatch_status == 'authorization_required' else 'not_established')
        # Do not emit exceptions/credentials or unlimited data in Chat receipts.
        receipt['result'] = (json.dumps(result, ensure_ascii=False, default=str)[:64000 if name in {'run_learning','recall_learning','run_paper_replay','read_paper_episode','cancel_paper_replay','read_trading_readiness','observe_trading','recall_trading_observations','run_execution_rehearsal','recall_execution_rehearsal','recall_environment_preparation'} else 5000]
                             if result is not None and receipt['status'] == 'success' else None)
        receipt['error'] = ('canonical_memory_unavailable' if isinstance(result,dict) and
                            str(result.get('error','')).startswith('canonical_memory_unavailable') else
                            'permission_denied' if dispatch_status=='authorization_required' else
                            'tool_unavailable_or_denied' if outcome.get('error') else None)
        receipts.append(receipt)
    return receipts


def evidence_reply(intent, facts, receipts):
    """Runtime claims come from observations, never probabilistic self-report."""
    if intent=='execution_rehearsal':
        if not receipts or receipts[0]['status']!='success':return 'Execution rehearsal unavailable or denied. No external order execution was authorized.'
        value=json.loads(receipts[0]['result'])
        lines=[value.get('summary','Execution rehearsal UNKNOWN.'),'Status: '+value['status']+'. All external delivery remains DENIED. '+('Preparation includes timestamped read-only observations and explicitly intercepted tests.' if value.get('record_type')=='environment_preparation' else 'Acknowledgements and outcomes below are simulated.')]
        for case in value.get('cases',[]):
            lines.append(f"{case['platform'].upper()} {case['case']}: passed={case['passed']}; intercepted calls={case['intercepted_calls']}; signal={case['signal']}; eligible rules={case.get('eligible_strategies')}; simulated net={case.get('net')}; limitation/error={case.get('error')}.")
            if case.get('net') is not None:
                lines.append('Intercepted entry: '+json.dumps(case.get('entry_order'))+'; exit: '+json.dumps(case.get('exit_order'))+
                    '; exit reason: '+str(case.get('exit_reason'))+'; simulated cost/risk: '+json.dumps(case.get('modeled_cost_risk')))
        lines.extend(value.get('limitations',[]))
        lines.append('External native send count: '+str(value.get('external_native_send_count','UNKNOWN'))+'; evidence '+value.get('evidence','UNKNOWN'))
        return '\n\n'.join(lines)
    if intent=='trading_readiness':
        if not receipts or receipts[0]['status']!='success':return 'UNKNOWN — authorized trading evidence unavailable. External execution remains DENIED.'
        value=json.loads(receipts[0]['result']);lines=['Recorded trading reconciliation. All new external execution remains DENIED.']
        for report in value.get('reports',[]):
            observation=report['observation']
            lines.append(report['platform'].upper()+' — '+observation['summary'])
            lines.extend(observation.get('findings',[]))
            lines.append('Observed at '+observation['observed_at']+'; evidence '+report['citation'])
        lines.append(value['limitation'])
        return '\n\n'.join(lines)
    if intent == 'paper_replay':
        if not receipts or receipts[0]['status'] != 'success':
            return 'Paper evaluation unavailable or permission denied. No paper execution is established by this response.'
        result=json.loads(receipts[0]['result'])
        lines=[f"Paper replay {result.get('run_id')}: {result.get('status')}."]
        if result.get('error'):lines.append(result['error'])
        if result.get('reason'):lines.append(result['reason'])
        for episode in result.get('scenarios',[]):
            lines.append(f"{episode['name']}: {episode['status']}; {episode['observations']} observations; "
                f"realized net {episode['realized_net']:.6f} USDT; fees {episode['fees']:.6f}; "
                f"open positions {episode['open_positions']}.")
            lines.append('Rules: '+', '.join(s['strategy']+'='+s['side'] for s in episode['signals']))
            for decision in episode['decisions']:
                lines.append(f"{decision['action']} ({decision['strategy']}): {decision['status']} "
                    f"[{decision['decision_id']}]"+(f" — {decision['error']}" if decision.get('error') else ''))
            for reason in episode['exit_reasons']:lines.append('Exit: '+reason)
            for actual in episode['actuals']:
                lines.append(f"Fill actuals: {actual['side']} {actual['quantity']:.6f} units; "
                    f"{actual['entry']} → {actual['exit']}; gross {actual['gross']:.6f} "
                    f"− fees {actual['fees']:.6f} = net {actual['net']:.6f} USDT.")
        if result.get('replayed_existing'):lines.append('Existing receipt retrieved. No new execution.')
        if result.get('cancellation_acknowledged_at'):
            lines.append('Worker cancellation acknowledged at '+datetime.fromtimestamp(
                result['cancellation_acknowledged_at'],timezone.utc).isoformat()+
                '. Existing simulated positions remain recorded; cancellation does not force an exit.')
        if result.get('evidence'):lines.append('Persistent evidence: '+result['evidence'])
        lines.extend(result.get('limitations',[]))
        if result.get('limitation'):lines.append(result['limitation'])
        lines.append('Simulated execution only. No broker orders. These results do not establish profitability or calibrated predictions.')
        return '\n\n'.join(lines)
    if intent == 'learned_application':
        if not receipts or receipts[0]['status']!='success':
            return 'UNKNOWN — canonical learning retrieval failed; no evidence-backed application was performed.'
        try:
            if not json.loads(receipts[0]['result']).get('facts'):
                return 'UNKNOWN — no authorized stored learning evidence was found for this subject.'
        except (ValueError,TypeError):
            return 'UNKNOWN — unreadable learning evidence.'
        return None
    if intent == 'learning_clarification':
        return ('For structured learning, provide a JSON workspace filename, scalar field names and a subject. '
                'For example: Learn name, version from file sample.json for subject my.project. '
                'For approved public research: Research inventory count adjustment and learn for subject retail.inventory. '
                'No learning tool was executed.')
    if intent in {'learning','learned_recall'}:
        if not receipts or receipts[0]['status'] != 'success':
            return 'Learning request not completed: ' + (receipts[0]['status']+' — '+str(receipts[0].get('error') or 'UNKNOWN')+' ['+receipts[0]['id']+'].' if receipts else 'tool unavailable.')
        try:
            result = json.loads(receipts[0]['result'])
        except (ValueError,TypeError):
            return 'UNKNOWN — the learning tool did not return a readable receipt.'
        if intent == 'learning':
            lines = [f"Learning investigation: {result.get('status','UNKNOWN')}. "
                     f"New records: {result.get('new_records',0)}; repeated observations: {result.get('repeated_observations',0)}."]
            lines.append('Subject: '+str(result.get('subject','UNKNOWN')))
            for item in result.get('accepted',[]):
                lines.append(f"{item.get('field')}: {json.dumps(item.get('value'),ensure_ascii=False)} — {item['status']}; evidence {item['id']}; {item['citation']}")
            if result.get('rejected'):lines.append('Rejected: '+json.dumps(result['rejected'],ensure_ascii=False))
            if result.get('unresolved'):lines.append('Unresolved/held for review: '+json.dumps(result['unresolved'],ensure_ascii=False))
            lines.append('Learning receipt: '+str(result.get('event_id','UNKNOWN'))+'. These are source declarations, not independently verified world facts.')
            if result.get('profile')=='public_sources':
                lines.append('Research scope: approved public-source excerpts; not general autonomous research. Publication dates and hardware-retail applicability remain UNKNOWN unless documented.')
                lines.append('Limitations: '+'; '.join(result.get('limitations',[])))
            return '\n'.join(lines)
        values = result.get('facts',[])
        if not values:return 'UNKNOWN — no authorized stored learning evidence was found for this subject.'
        lines = [f"Stored source observations for {result['subject']}:"]
        for item in values:
            lines.append(f"{item['field']}: {json.dumps(item['value'],ensure_ascii=False)} [evidence {item['id']}; {item['citation']}]")
        mapping = {item['field']:item['value'] for item in values}
        if 'name' in mapping and 'version' in mapping:
            lines.append(f"Application — name@version label: {mapping['name']}@{mapping['version']}")
        return '\n'.join(lines)
    if intent == 'authorization_required':
        return ('This action is outside automatic read-only Chat execution. Use the existing '
                'governed command controls and their required authorization. No action was executed.')
    if intent in {'file', 'research'} and any(r['status'] != 'success' for r in receipts):
        return 'The read-only request did not complete:\n' + '\n'.join(
            f"{r['tool']}: {r['status']} [{r['id']}]. {r['error'] or 'UNKNOWN'}" for r in receipts)
    if intent in {'identity', 'identity_challenge'}:
        models = ', '.join(facts['available_models']) or 'UNKNOWN'
        prefix = ('You are right to question unsupported claims. ' if intent == 'identity_challenge' else '')
        return (prefix + 'Niblit Core is the cognitive controller. The configured gateway currently reports '
                f"provider {facts['provider']}, available model {models}, endpoint {facts['endpoint']}. "
                'This response was assembled from runtime evidence; no generative model produced its text '
                'and no fallback was used. A loaded model does not prove which model generated an earlier reply. '
                f"Evidence: inference observation at {facts['observed_at']}.")
    if intent == 'diagnostic':
        lines = ['Completed the bounded read-only assessment:']
        for receipt in receipts:
            lines.append(f"- {receipt['tool']}: {receipt['status']} [{receipt['id']}]. "
                         + (receipt['result'] or receipt['error'] or 'UNKNOWN'))
        lines.append('Not tested: broker execution, full learning cycle, privileged operations or all registered capabilities. '
                     'Tool dispatch success alone does not verify every subsystem mentioned in its output.')
        return '\n'.join(lines)
    return None
