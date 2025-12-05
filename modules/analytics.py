# modules/analytics.py
from collections import Counter

class AnalyticsModule:
    def __init__(self, db):
        self.db = db

    def analyze_text(self, text):
        # light-weight analysis: token stats and common words
        toks = [t.strip('.,!?').lower() for t in text.split() if t.strip()]
        if not toks:
            return 'No text to analyze.'
        ctr = Counter(toks)
        top = ctr.most_common(8)
        return f"Tokens: {len(toks)}. Top words: {', '.join([w for w,_ in top])}."

    # placeholder for financial/marketing/biological analysis
    def analyze_numbers(self, numbers):
        try:
            nums = [float(x) for x in numbers]
            return {'count':len(nums),'mean':sum(nums)/len(nums)}
        except Exception:
            return {'error':'invalid numbers'}
