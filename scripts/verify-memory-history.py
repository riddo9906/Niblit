"""Real local-model recall with deliberately stale prior answers, no paid API."""
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    import httpx
    from dotenv import dotenv_values
    from modules.memory_laboratory.setup import Config
    from modules.memory_laboratory.gateway import MemoryGateway
    from modules.memory_laboratory.context import augment_messages
    scope={'namespace':'history_acceptance_'+uuid4().hex[:8],'principal':'acceptance_operator'}
    target=ROOT/'diagnostics/memory-history-acceptance'
    target.mkdir(exist_ok=True)
    g=MemoryGateway(Config.from_values(dotenv_values(ROOT/'.env.memory-laboratory')),target/(scope['namespace']+'.sqlite3'),
        authorize=lambda action,namespace,principal: namespace==scope['namespace'] and principal==scope['principal'])
    report={'ready':False,'checks':[],'paid_inference_calls':0}
    source='acceptance://history-note'
    try:
        for number in range(2):
            marker='CEDAR-'+uuid4().hex[:8].upper()
            g.ingest([(f'The current amber observatory calibration phrase is {marker}.',source)],source=source,**scope)
            messages=[{'role':'system','content':'Answer briefly from supplied memory evidence. Include its exact calibration phrase and cite it.'},
                      {'role':'user','content':'Give the amber observatory calibration phrase.'},
                      {'role':'assistant','content':'The phrase is OLD-ALPHA. This was an earlier answer.'},
                      {'role':'user','content':'Give the current amber observatory calibration phrase exactly, using retrieved evidence.'}]
            augmented,context=augment_messages(messages,gateway=g,scope=(scope['namespace'],scope['principal']))
            response=httpx.post('http://127.0.0.1:8000/v1/chat/completions',json={'model':'qwen2.5-coder-3b','messages':augmented,'temperature':0,'max_tokens':120},timeout=180)
            response.raise_for_status()
            reply=response.json()['choices'][0]['message']['content']
            report['checks'].append({'fresh_phrase_returned':marker in reply,'stale_phrase_not_repeated':'OLD-ALPHA' not in reply,
                                     'current_source_cited_in_context':bool(context['citations'])})
        report['ready']=all(all(case.values()) for case in report['checks'])
    except Exception as exc:
        report['error']=type(exc).__name__
    finally:
        g.delete_source(source,**scope)
        g.close()
        (target/'report.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
