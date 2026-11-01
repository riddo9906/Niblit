"""One small explicit inference probe, with metadata-only diagnostics."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
root = Path(__file__).resolve().parents[1]
load_dotenv(root / '.env')
from modules.steward_agent import StewardBridge

registration = json.loads((root / 'agents/niblit-steward/registration.json').read_text())
report = {'registered': registration.get('registered'), 'inference_verified': False}
try:
    result = StewardBridge().request('POST', '/sessions', {
        'agent_id': registration['agent_id'], 'environment': {'type': 'none'},
        'input': 'Do not use tools. State your mentoring role in one short sentence.'})
    report.update(session_id=result.get('id'), status=result.get('status'), response_fields=sorted(result))
except RuntimeError as exc:
    report['error'] = str(exc)
(root / 'diagnostics/steward-connection-20261028.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
