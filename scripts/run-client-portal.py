"""Bootstrap an admin interactively; then run the isolated shared portal."""
from pathlib import Path
import argparse
import getpass
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from modules.server_manager import ServerManager, create_app

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--create-admin',action='store_true')
    parser.add_argument('--origin',default=os.environ.get('NIBLIT_PORTAL_ORIGIN','http://127.0.0.1:8768'))
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8768')))
    args=parser.parse_args()
    data=Path(os.environ.get('NIBLIT_PORTAL_DATA',str(ROOT/'runtime/client-portal')))
    manager=ServerManager(data/'session.sqlite3')
    if args.create_admin:
        manager.add_user(input('Administrator username: ').strip(),getpass.getpass('New password (12+ characters): '),'admin')
        print('Administrator created. Start without --create-admin to serve.')
    else:
        import uvicorn
        uvicorn.run(create_app(manager,args.origin),host=args.host,port=args.port,proxy_headers=False)
