"""Read-only FreqUI callback adapter for Core-generated plot snapshots."""
import hashlib,json,time
from pathlib import Path

def read_plot_annotations(config,pair,timeframe):
    try:
        root=Path(config['user_data_dir'])
        path=root/'niblit_chart_annotations'/(hashlib.sha256((pair+'|'+timeframe).encode()).hexdigest()+'.json')
        if path.stat().st_size>150000:return []
        data=json.loads(path.read_text(encoding='utf-8'))
        profile=root/'config.json'
        scope=data['scope'];expected_mode='dry-run' if config.get('dry_run') is True else 'observe'
        if (data.get('schema')!='niblit.frequi.v1' or scope['symbol']!=pair or scope['timeframe']!=timeframe
            or scope['mode']!=expected_mode or data.get('execution_authorized') is not False
            or data.get('core_authorization',{}).get('allowed') is not True
            or data.get('profile_sha256')!=hashlib.sha256(profile.read_bytes()).hexdigest()):return []
        result=data['annotations']
        if not isinstance(result,list) or len(result)>80:return []
        for a in result:
            if a.get('type') not in ('area','line','point'):return []
            if time.time()>data['expires_at']:a['label']='[historical snapshot] '+a.get('label','')
        return result
    except (OSError,ValueError,KeyError,TypeError):return []
