# server.py
from flask import Flask, request, jsonify, render_template_string
from niblit_core import NiblitCore
import threading

app = Flask("niblit_server")
n = NiblitCore()

# Simple HTML dashboard template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Niblit Dashboard</title>
<style>
body { font-family: Arial, sans-serif; background:#1b1b1b; color:#f1f1f1; }
.container { width: 90%; max-width: 900px; margin:auto; padding:20px; }
textarea { width:100%; height:80px; background:#222; color:#f1f1f1; border:none; padding:10px; }
button { padding:10px 20px; margin-top:10px; background:#444; color:#f1f1f1; border:none; cursor:pointer; }
#chatbox { border:1px solid #333; padding:10px; height:300px; overflow-y:scroll; background:#111; margin-top:10px;}
.chat-msg { margin:5px 0; }
.user { color:#4ef; }
.bot { color:#fa4; }
</style>
</head>
<body>
<div class="container">
<h1>Niblit Dashboard</h1>
<p>System Status: <span id="status">Initializing...</span></p>

<textarea id="input" placeholder="Type a command or question..."></textarea><br>
<button onclick="send()">Send</button>

<div id="chatbox"></div>

<script>
async function send() {
    let input = document.getElementById("input").value;
    if(!input) return;
    let chatbox = document.getElementById("chatbox");
    chatbox.innerHTML += '<div class="chat-msg user">You: ' + input + '</div>';
    document.getElementById("input").value = '';

    let resp = await fetch("/chat", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({text:input})
    });
    let data = await resp.json();
    chatbox.innerHTML += '<div class="chat-msg bot">Niblit: ' + (data.reply || '[no reply]') + '</div>';
    chatbox.scrollTop = chatbox.scrollHeight;
}

async function checkStatus() {
    let resp = await fetch("/ping");
    let data = await resp.json();
    document.getElementById("status").innerText = "OK - Personality mood: " + (data.personality.mood || "neutral");
}
setInterval(checkStatus, 5000);
checkStatus();
</script>
</div>
</body>
</html>
"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status":"ok","personality": n.db.get_personality()})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text","").strip()
    if not text:
        return jsonify({"error":"no text provided"}), 400
    reply = n.handle(text)
    return jsonify({"reply": reply})

@app.route("/memory", methods=["GET"])
def memory():
    facts = n.db.list_facts(limit=200)
    return jsonify({"facts": facts})

def run_server():
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    print("Starting Niblit HTTP server on http://0.0.0.0:5000")
    run_server()
