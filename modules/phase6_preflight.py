"""Offline packaged acceptance: temporary ledger and broker doubles only."""
import json
from pathlib import Path
import tempfile
from modules.memory_laboratory.setup import Config
from modules.memory_laboratory.gateway import MemoryGateway
from modules.memory_laboratory.runtime import MemoryRuntime
from modules.memory_laboratory.cognitive import CognitiveMemory
from modules.observation_supervisor import ObservationJob,ObservationSupervisor


def main():
    class Offline:
        def __init__(self):self.embedder=self
        def close(self):pass
        def embed(self,*a,**k):raise AssertionError('Offline preflight forbids embeddings')
    with tempfile.TemporaryDirectory(prefix='niblit-phase6-preflight-') as directory:
        gateway=MemoryGateway(Config(url='http://127.0.0.1:6333'),Path(directory)/'fixture.sqlite3',
            setup=Offline(),authorize=lambda *a:True)
        try:
            memory=CognitiveMemory(MemoryRuntime(gateway))
            event=dict(domain='diagnostics',event_id='fixture',source='offline:fixture',
                observed_at='2026-11-12T00:00:00Z',available_at='2026-11-12T00:00:00Z',
                content='Synthetic offline fixture, not a broker observation.')
            first=memory.record(**event);second=memory.record(**event)
            assert first['id']==second['id'] and second['duplicate']
            assert len(memory.retrieve(domain='diagnostics',as_of='2026-11-12T01:00:00Z'))==1
            job=ObservationJob('desktop','FIXTURE','fixture','fixture')
            observer=ObservationSupervisor([job],{'desktop':lambda j:{'connected':True,
                'account':{'identity':'fixture','terminal_id':'fixture'},'symbol':'FIXTURE',
                'received_at':100,'fresh':True,'execution_authorized':False}},clock=lambda:100)
            assert observer.poll_source('desktop') and observer.status()['jobs'][0]['fresh']
            from modules.market_prediction import forecast, walk_forward
            fixture={'fresh':True,'utc_clock_verified':True,'symbol':'FIXTURE','account':{'identity':'fixture','terminal_id':'fixture','server':'fixture','environment':'demo'},'prediction_inputs':{'candles':[{'timestamp':i*300,'close':100+i} for i in range(7)]},'evidence':{'M5':{'source':{},'snapshot_id':'fixture'}},'quote':{}}
            prediction=forecast(fixture,900,2110)
            assert prediction['probability'] is None and not prediction['execution_authorized']
            assert walk_forward([{'timestamp':i*300,'close':100+i} for i in range(100)])['net_profit'] is None
            print(json.dumps({'schema_version':'phase6-preflight/1','passed':True,
                'shadow_prediction_contract':True,'canonical_idempotence':True,'temporal_retrieval':True,'source_binding':True,
                'broker_connector_created':False,'orders_sent':0,'production_store_opened':False}))
        finally:gateway.close()
    return 0
