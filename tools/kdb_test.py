import sys
import json
import os
from pathlib import Path

# Ensure imports resolve when running this script from the repo root or
# from the `Niblit/tools` directory: add the repository root and the
# `Niblit` package directory to `sys.path` so `shared` and `niblit_memory`
# imports succeed.
_THIS = Path(__file__).resolve()
repo_root = _THIS.parents[2]
niblit_dir = _THIS.parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(niblit_dir))

from niblit_memory import KnowledgeDB

TEST_PATH = os.path.join(os.path.dirname(__file__), 'test_kdb.json')
# Remove existing test file
try:
    os.remove(TEST_PATH)
except Exception:
    pass

k = KnowledgeDB(path=TEST_PATH)
# Add duplicate research facts
k.add_fact('research:primary colors', {'colors': ['red']}, tags=['research'])
k.add_fact('research:primary colors', {'colors': ['red','green']}, tags=['research'])
# Add via store_research duplicates
k.store_research('research_response:primary colors', 'blue text', tags=['research'], source='web')
k.store_research('research_response:primary colors', 'blue text v2', tags=['research'], source='web')
# Queue-like key snapshots
k.add_fact('self_teacher:review_queue', {'queue': ['a']}, tags=['review-queue'])
k.add_fact('self_teacher:review_queue', {'queue': ['a','b']}, tags=['review-queue'])

# Ensure persisted
k.shutdown()

# Load and check duplicates
with open(TEST_PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

facts = data.get('facts', [])
counts = {}
for f in facts:
    if isinstance(f, dict):
        kf = f.get('key')
        counts[kf] = counts.get(kf, 0) + 1

print('TOTAL_FACTS', len(facts))
for kkey, cnt in counts.items():
    print(kkey, cnt)

# Print fact entries for our test keys
for key in ['research:primary colors', 'research_response:primary colors', 'self_teacher:review_queue']:
    print('\n--', key)
    for f in facts:
        if isinstance(f, dict) and f.get('key') == key:
            print(f)
