"""Read-only acceptance for the R14 redesigned Market Desk assets."""
from pathlib import Path
from bs4 import BeautifulSoup
import subprocess
import hashlib
import urllib.request
root=Path(r"C:\Users\Riyaad\Documents\GitHub\Niblit\assets\trading-desk")
bundle=Path(r"D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\assets\trading-desk")
html=BeautifulSoup((root/"index.html").read_text(encoding="utf-8"),"html.parser")
ids=[x.get("id") for x in html.select("[id]")]
assert len(ids)==len(set(ids)), "Duplicate HTML controls"
mandatory=("desk-overview","demo-activation-guide","desk-core-health","desk-blocker-summary",
 "core-readiness-result","core-propose","core-activate","core-execution-symbol","core-demo-volume",
 "core-positions","auto-minutes","mt5-workspace","mt5-positions")
assert all(x in ids for x in mandatory)
assert html.select_one("#core-execution-symbol")["value"]=="ETHUSDm"
assert html.select_one("#core-demo-volume")["value"]=="0.10"
assert html.select_one("#core-positions")["value"]=="2"
assert html.select_one("#auto-minutes")["value"]=="60"
assert len(html.select(".demo-steps li"))==3
assert html.select_one("#core-readiness-result").name=="div"
for name in ("index.html","desk.css","sessions.js"):
    source=(root/name).read_bytes()
    staged=(bundle/name).read_bytes()
    assert source==staged,f"Packaged asset diverges: {name}"
    print(name,"sha256",hashlib.sha256(staged).hexdigest(),"bytes",len(staged))
js=(root/"sessions.js").read_text(encoding="utf-8")
css=(root/"desk.css").read_text(encoding="utf-8")
assert "Niblit R14 modern Market Desk presentation" in js
assert "readiness-status" in js and "Review requires attention" in js
assert "body[data-remote-observation] .desk-content" in css
assert "r9.1 VERIFICATION MODE" not in js
check=subprocess.run(["node","--check",str(root/"sessions.js")],capture_output=True,text=True)
assert check.returncode==0,check.stderr
for route,needle in (("/market-desk/","desk-overview"),("/market-desk/desk.css","desk-overview"),("/market-desk/sessions.js","Niblit R14 modern Market Desk presentation")):
    with urllib.request.urlopen("http://127.0.0.1:5202"+route,timeout=10) as response:
        body=response.read().decode("utf-8")
        assert response.status==200 and needle in body,route
        print("HTTP_OK",route)
print("R14_MODERN_MARKET_DESK_ACCEPTED")
