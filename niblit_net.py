# niblit_net.py - simple raw fetch utilities
import urllib.request, urllib.error, json
def fetch_data(url):
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            return resp.read().decode(errors="ignore")
    except Exception as e:
        return f"[FETCH ERROR] {e}"

def learn_from_data(text):
    # placeholder - analyze & store
    return {"summary": text[:100]}


if __name__ == "__main__":
    import sys
    print("=== niblit_net self-test ===")
    # Test learn_from_data locally (no network required)
    result = learn_from_data("The quick brown fox jumps over the lazy dog")
    print(f"learn_from_data summary: {result['summary']!r}")
    # Attempt a real fetch only if a URL is passed as argument
    if len(sys.argv) > 1:
        url = sys.argv[1]
        print(f"Fetching {url} ...")
        data = fetch_data(url)
        print(data[:200])
    print("niblit_net OK")
