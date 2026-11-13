import json,subprocess
from pathlib import Path

def test_live_launcher_refuses_engine_control_before_any_side_effect(tmp_path):
    source=Path(__file__).resolve().parents[1]/'scripts/Start-Niblit-Freqtrade.ps1'
    profile=tmp_path/'live.json';profile.write_text(json.dumps({'dry_run':False}),encoding='utf-8')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(source),'-ConfigPath',str(profile),'-EnableTradingControls'],capture_output=True,text=True)
    assert result.returncode!=0
    assert 'Real-money engine controls are disabled' in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir())==['live.json']

def test_live_shortcut_never_requests_engine_control():
    source=Path(__file__).resolve().parents[1]/'scripts/Start-Niblit-Live.cmd'
    assert '-EnableTradingControls' not in source.read_text(encoding='utf-8-sig')
