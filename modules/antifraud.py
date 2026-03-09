import re

class AntiFraudModule:
    def __init__(self, db):
        self.db = db

    def check(self, text):
        low = text.lower()
        alerts = []
        if 'bank' in low and 'password' in low:
            alerts.append('Possible credential phishing mention.')
        if 'transfer' in low and ('urgent' in low or 'immediately' in low):
            alerts.append('Urgent transfer language — common scam pattern.')
        if re.search(r'\b\d{12,}\b', low):
            alerts.append('Long digit sequence detected (possible account/cc).')
        if not alerts:
            return 'No obvious fraud patterns detected.'
        for a in alerts:
            self.db.add_fact('antifraud:alert', a, tags=['antifraud'])
        return ' | '.join(alerts)
if __name__ == "__main__":
    print('Running antifraud.py')
