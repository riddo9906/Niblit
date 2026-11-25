import os,time
os.environ["NIBLIT_MOBILE_GATEWAY_AUTOSTART"]="1"
os.environ["NIBLIT_API_PORT"]="5202"
os.environ["NIBLIT_PORTAL_DB_PATH"]=r"D:\NiblitAIOS\data\client-portal\session.sqlite3"
from modules.mobile_runtime_service import start_mobile_gateway
gateway=start_mobile_gateway()
assert gateway is not None
for i in range(45):
    if gateway[0].should_exit:
        raise SystemExit("Gateway terminated unexpectedly")
    time.sleep(1)
