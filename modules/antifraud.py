# modules/antifraud.py
import re

class AntiFraudModule:
    def __init__(self, db):
        self.db = db

    def check(self, text):
        # heuristic checks: look for common scam patterns
        low = text.lower()
        alerts = []
        if 'bank' in low and 'password' in low:
            alerts.append('Possible credential phishing mention.')
        if 'transfer' in low and ('urgent' in low or 'immediately' in low):
            alerts.append('Urgent transfer language — common scam pattern.')
        if re.search(r'\b\d{12,}\b', low):
            alerts.append('Long digit sequence detected (possible account/cc).')
        # add ML model hook placeholder
        if not alerts:
            return 'No obvious fraud patterns detected.'
        # store alert example
        for a in alerts:
            self.db.add_fact('antifraud:alert', a, tags=['antifraud'])
        return ' | '.join(alerts)
