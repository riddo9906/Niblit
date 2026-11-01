"""Serve the local memory control desk without creating another inference worker."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__ == '__main__':
    # One bounded embedding worker, no Core/ALE or second generation model.
    os.environ.setdefault('OMP_NUM_THREADS','1')
    os.environ.setdefault('MKL_NUM_THREADS','1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
    os.environ['NIBLIT_MEMORY_EMBEDDING_THREADS']='1'
    from dotenv import dotenv_values
    values=dotenv_values(ROOT/'.env')
    if values.get('NIBLIT_PERMISSION_FILE'):
        os.environ['NIBLIT_PERMISSION_FILE']=values['NIBLIT_PERMISSION_FILE']
    import uvicorn
    from modules.memory_laboratory.web import create_app
    uvicorn.run(create_app(port=8772),host='127.0.0.1',port=8772,log_level='warning')
