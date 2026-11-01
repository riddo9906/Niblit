"""Build a source-only atlas without importing or executing Niblit modules.

What: enumerate first-party source, Python symbols and review signals.
How: walk explicit repositories, skip generated/runtime/vendor trees, parse AST.
Why: give maintainers reproducible source references, not guessed capability claims.
Syntax errors and pass/ellipsis bodies are review leads, not automatic defects.
"""
import ast
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPOS=('Niblit','Niblit-cloud-server','niblit-ui','niblit-lean-algos','niblit-steward','trade-signal-desk','github-copilot-llm-gateway','niblit-website')
SKIP={'.git','.venv','venv','env','niblit-env','node_modules','dist','build','target','runtime','diagnostics','__pycache__','.pytest_cache','.next','.openai','vendor','third_party','site-packages','models','.cache','coverage'}
EXT={'.py','.ts','.tsx','.js','.mjs','.cjs','.jsx','.rs','.ps1','.sh','.cmd','.html','.css'}


def inspect(path,repo):
    text=path.read_text(encoding='utf-8-sig',errors='replace')
    row={'path':path.relative_to(repo).as_posix(),'lines':len(text.splitlines()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'language':path.suffix,'symbols':[],'review':[]}
    if path.suffix!='.py':
        return row
    try:
        tree=ast.parse(text)
    except SyntaxError as e:
        row['review'].append({'kind':'syntax','line':e.lineno,'detail':e.msg})
        return row
    row['summary']=(ast.get_docstring(tree) or '').split('\n')[0][:240]
    for parent in [tree,*[n for n in ast.walk(tree) if isinstance(n,ast.ClassDef)]]:
        names={}
        for node in parent.body:
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                continue
            name=(parent.name+'.' if isinstance(parent,ast.ClassDef) else '')+node.name
            doc=ast.get_docstring(node) or ''
            row['symbols'].append({'name':name,'line':node.lineno,'kind':type(node).__name__,'summary':doc.split('\n')[0][:200]})
            if node.name in names:
                row['review'].append({'kind':'duplicate-definition','line':node.lineno,'name':name,'previous_line':names[node.name]})
            names[node.name]=node.lineno
            body=node.body[1:] if ast.get_docstring(node) else node.body
            if body and all(isinstance(n,ast.Pass) or (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and n.value.value is Ellipsis) for n in body):
                row['review'].append({'kind':'empty-body','line':node.lineno,'name':name})
    return row


def main():
    out=ROOT/'docs/code-atlas';out.mkdir(parents=True,exist_ok=True)
    catalog={}
    for name in REPOS:
        repo=ROOT.parent/name
        if not repo.exists():
            continue
        rows=[]
        for base,dirs,files in os.walk(repo,followlinks=False):
            dirs[:]=sorted(d for d in dirs if (d not in SKIP or (d=='dist' and name in ('trade-signal-desk','niblit-website'))) and not d.startswith('.'))
            for filename in sorted(files):
                p=Path(base)/filename
                if p.is_symlink() or p.suffix not in EXT or p.stat().st_size>2_000_000:
                    continue
                rows.append(inspect(p,repo))
        catalog[name]=rows
        md=[f'# {name} source atlas','', 'Generated from source without importing modules. Definitions and docstrings are navigation aids, not proof that the feature works. Review signals need human inspection. Generated, runtime, model, vendor and environment directories are excluded.','', '| Source | Lines | Symbols | Review signals |','|---|---:|---:|---:|']
        for r in rows:
            md.append(f"| [{r['path']}](../../../{name}/{r['path']}) | {r['lines']} | {len(r['symbols'])} | {len(r['review'])} |")
        md+=['','## Python definitions','']
        for r in rows:
            if not r['symbols'] and not r['review']:
                continue
            md += [f"### {r['path']}",'',r.get('summary') or 'Module purpose needs a human explanation.','']
            md += [f"- `{s['name']}` at line {s['line']}: {s['summary'] or 'Explanation needed.'}" for s in r['symbols']]
            md += [f"- Review: {s['kind']} at line {s.get('line')}." for s in r['review']]
            md.append('')
        (out/(name+'.md')).write_text('\n'.join(md),encoding='utf-8')
    (out/'index.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
    summary={name:{'files':len(rows),'lines':sum(r['lines'] for r in rows),'symbols':sum(len(r['symbols']) for r in rows),'documented_symbols':sum(bool(s['summary']) for r in rows for s in r['symbols']),'review_signals':sum(len(r['review']) for r in rows)} for name,rows in catalog.items()}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
