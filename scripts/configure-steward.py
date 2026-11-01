"""Export or explicitly register Niblit Steward without printing credentials."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from modules.steward_agent import StewardBridge, configuration
from modules.environment_navigator import FUNCTION, SCHEMA

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--register', action='store_true')
parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'agents' / 'niblit-steward')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
for name, value in [('agent.json', configuration()), ('function.json', FUNCTION), ('chat-function.json', SCHEMA)]:
    (args.output / name).write_text(json.dumps(value, indent=2), encoding='utf-8')
result = {'exported': True, 'registered': False}
if args.register:
    try:
        result.update(StewardBridge().register(), registered=True)
    except RuntimeError as exc:
        result['error'] = str(exc)
    (args.output / 'registration.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
