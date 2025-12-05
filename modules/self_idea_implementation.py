# modules/self_idea_implementation.py
class SelfIdeaImplementation:
    def __init__(self, db):
        self.db = db

    def implement_ideas(self, limit=10):
        ideas = [f for f in self.db.list_facts(200) if f['key'].startswith('idea:')]
        implemented = 0
        for i, item in enumerate(ideas[:limit]):
            k = item['key'].replace('idea:', 'implemented:')
            self.db.add_fact(k, item['value'], tags=item.get('tags',[])+['implemented'])
            implemented += 1
        return f"Implemented {implemented} ideas into facts."
