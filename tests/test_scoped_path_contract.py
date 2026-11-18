"""Existing filesystem resolver interoperability; not relocation acceptance."""
import importlib.util
from pathlib import Path
import ast

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('scoped_existing_paths',ROOT/'niblit_core/config/paths.py')
paths=importlib.util.module_from_spec(spec);spec.loader.exec_module(paths)

def test_absolute_external_paths_are_not_rebased_to_source(tmp_path):
    assert paths.resolve_path(str(tmp_path/'memory.sqlite3')) == tmp_path/'memory.sqlite3'
    assert paths.get_project_root() == ROOT

def test_absolute_windows_cross_drive_resources():
    if __import__('os').name!='nt':return
    for resource in ['C:/approved/models/model.gguf','D:/approved/candidate/niblit.exe']:
        assert paths.resolve_path(resource)==Path(resource)

def test_existing_specs_resolve_source_from_spec_location():
    for repo,filename in [('Niblit','niblit.spec'),('Niblit-cloud-server','niblit-cloud-server.spec'),('niblit-lean-algos','niblit-lean-algos.spec'),('niblit-lean-algos','freqtrade_worker.spec')]:
        text=(ROOT.parent/repo/filename).read_text(encoding='utf-8-sig')
        ast.parse(text)
        assert 'Path(SPECPATH).resolve()' in text

def test_native_model_and_memory_data_are_not_build_environment_overrides():
    text=(ROOT/'scripts/build-paths.js').read_text()
    assignments=text.split('function buildEnvironment',1)[1]
    for forbidden in ['QDRANT_URL:', 'NIBLIT_MEMORY_PATH:', 'NIBLIT_PORTAL_GGUF_URL:', 'NIBLIT_EXECUTION_ENABLED:']:
        assert forbidden not in assignments
