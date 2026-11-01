"""Run the isolated, local manual market workspace (no inference loop)."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if __name__=='__main__':
    import os
    from dotenv import dotenv_values
    terminal=dotenv_values(ROOT/'.env').get('NIBLIT_MT5_TERMINAL')
    if terminal:
        os.environ.setdefault('NIBLIT_MT5_TERMINAL',terminal)
    import uvicorn
    from modules.trading_desk import create_app
    uvicorn.run(create_app(),host='127.0.0.1',port=8767,log_level='warning')
