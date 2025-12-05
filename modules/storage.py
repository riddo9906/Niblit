# modules/storage.py
import json, os, time

def now_ts():
    return int(time.time())

class KnowledgeDB:
    def __init__(self, path='niblit_memory.json'):
        self.path = path
        self.data = {
            'facts': [],
            'interactions': [],
            'personality': {'mood':'neutral','verbosity':'medium'},
            'meta': {}
        }
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path,'r',encoding='utf-8') as f:
                    self.data = json.load(f)
        except Exception:
            # backup and re-init
            try:
                os.rename(self.path, self.path + '.bak')
            except Exception:
                pass
            self._save()

    def _save(self):
        with open(self.path,'w',encoding='utf-8') as f:
            json.dump(self.data,f,indent=2,ensure_ascii=False)

    # facts
    def add_fact(self,key,value,tags=None):
        tags = tags or []
        self.data['facts'].append({'key':key,'value':value,'tags':tags,'ts':now_ts()})
        self._save()

    def forget(self,key):
        before = len(self.data['facts'])
        self.data['facts'] = [f for f in self.data['facts'] if f['key'] != key]
        self._save()
        return before - len(self.data['facts'])

    def list_facts(self,limit=50):
        return list(reversed(self.data['facts'][-limit:]))

    # interactions
    def add_interaction(self,role,text):
        self.data['interactions'].append({'ts':now_ts(),'role':role,'text':text})
        if len(self.data['interactions'])>500:
            self.data['interactions']=self.data['interactions'][-500:]
        self._save()

    def recent_interactions(self,n=20):
        return self.data['interactions'][-n:]

    def get_personality(self):
        return self.data.get('personality',{})

    def condense(self,keep_top=20):
        # very simple condense: top words from interactions
        texts = ' '.join([it['text'] for it in self.data['interactions'] if it['role']=='user'])
        toks = [t.lower().strip('.,!?') for t in texts.split() if len(t)>3]
        from collections import Counter
        top = Counter(toks).most_common(keep_top)
        condensed = [{'key':f'common_{i+1}','value':w,'tags':['condensed'],'ts':now_ts()} for i,(w,_) in enumerate(top)]
        self.data['facts'] = condensed + self.data['facts']
        self._save()
        return condensed
