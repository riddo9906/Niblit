import os

class CounterActiveMembrane:
    def __init__(self, db):
        self.db = db

    def monitor(self):
        facts = len(self.db.data.get('facts',[]))
        interactions = len(self.db.data.get('interactions',[]))
        llm_key = bool(os.getenv('HF_TOKEN'))
        return {"facts":facts,"interactions":interactions,"llm_key_present":llm_key}
if __name__ == "__main__":
    print('Running counter_active_membrane.py')
