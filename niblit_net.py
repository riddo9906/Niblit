# niblit_net.py
import requests, re, html
WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
DUCK_API = "https://api.duckduckgo.com/?q={}&format=json"

def _split_text(text, max_sentences=6):
    text = re.sub(r'\s+', ' ', html.unescape(text or ''))
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()][:max_sentences]

def fetch_data(topic: str):
    topic_clean = topic.strip().replace(' ', '_')
    # Try Wikipedia summary
    try:
        r = requests.get(WIKI_API.format(topic_clean), timeout=6)
        if r.status_code == 200:
            js = r.json()
            if js.get('extract'):
                return _split_text(js.get('extract'))
    except Exception:
        pass
    # Try DuckDuckGo instant answer
    try:
        q = topic.replace('_', ' ')
        r = requests.get(DUCK_API.format(q), timeout=6)
        if r.status_code == 200:
            js = r.json()
            if js.get('AbstractText'):
                return _split_text(js.get('AbstractText'))
    except Exception:
        pass
    # fallback: return a helpful hint for manual web lookup
    return [f"No web data found for {topic}. Try checking Wikipedia or a search engine."]
    
def learn_from_data(data):
    print(f"[niblit_net] learned {len(data)} lines from web")
