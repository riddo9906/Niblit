"""Platform views of the original Core chart contract. No execution methods."""
import hashlib,json,math,re,threading,time
from pathlib import Path

def freqtrade_annotations(bundle):
    """Installed Freqtrade2026.9 line/point/area view shapes."""
    from datetime import datetime,timezone
    result=[]
    def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat()
    for a in bundle.get('annotations',[]):
        x=a['anchors'][0];y=a['anchors'][-1];common={'color':a['style']['color'],'label':'Niblit / '+a['strategy_id']+': '+(a.get('assessment') or a.get('signal') or a['role'])}
        if a['type']=='zone':
            result.append({**common,'type':'area','start':iso(x['time']),'end':iso(y['time']),'y_start':min(x['price'],y['price']),'y_end':max(x['price'],y['price'])})
        elif a['type'] in ('level','entry','stop','target','invalidation','trendline','ray'):
            result.append({**common,'type':'line','start':iso(x['time']),'end':iso(y['time'] if len(a['anchors'])==2 else x['time']+300),'y_start':x['price'],'y_end':y['price'],'width':1,'line_style':'dashed' if a['style'].get('dash') else 'solid'})
        else:result.append({**common,'type':'point','x':iso(x['time']),'y':x['price'],'shape':'circle','size':5})
    return result

def pine_export(bundle):
    """Snapshot-only supported Pine drawings. Never remote-control native tools."""
    def quoted(text):return json.dumps(str(text)[:400],ensure_ascii=True)
    frame={'1m':'1','5m':'5','15m':'15','1h':'60'}.get(bundle.get('scope',{}).get('timeframe'),'5')
    lines=['//@version=6','indicator("Niblit evidence snapshot", overlay=true, max_lines_count=100, max_labels_count=100, max_boxes_count=100)',
           '// Exported snapshot: refresh this export after a new Niblit observation.',
           '// Completed-candle references. Plotted candle time is not evidence of an advance prediction.',
           '// Instrument mapping is explicit: exchange futures and broker spot are not interchangeable.',
           'expectedTicker = input.string("", "Exact TradingView tickerid (required)")',
           'if barstate.islast', '    while array.size(line.all) > 0', '        line.delete(array.get(line.all, 0))', '    while array.size(label.all) > 0', '        label.delete(array.get(label.all, 0))', '    while array.size(box.all) > 0', '        box.delete(array.get(box.all, 0))', 'if barstate.islast and expectedTicker != "" and syminfo.tickerid == expectedTicker and timeframe.period == '+quoted(frame)]
    for a in bundle.get('annotations',[])[:80]:
        x=a['anchors'][0];t=int(x['time']*1000);p=x['price'];text=quoted(a['strategy_id']+' '+a['role']+': '+a['explanation']+'; Niblit observed UTC epoch '+str(a['observed_at'])+'; candle available '+str(a.get('source_available_at','legacy')));color='color.rgb('+','.join(str(int(a['style']['color'][i:i+2],16)) for i in (1,3,5))+')'
        if a['type'] in ('level','entry','stop','target','invalidation'):
            lines.append(f'    line.new({t}, {p}, {t+300000}, {p}, xloc=xloc.bar_time, extend=extend.right, color={color})')
        elif a['type'] in ('trendline','ray','zone'):
            y=a['anchors'][1];u=int(y['time']*1000)
            if a['type']=='zone':lines.append(f'    box.new({t}, {max(p,y["price"])}, {u}, {min(p,y["price"])}, xloc=xloc.bar_time, bgcolor=color.new({color}, 85), border_color={color})')
            else:lines.append(f'    line.new({t}, {p}, {u}, {y["price"]}, xloc=xloc.bar_time, color={color})')
        else:lines.append(f'    label.new({t}, {p}, {quoted(a.get("signal") or a["role"])}, xloc=xloc.bar_time, tooltip={text}, color={color}, textcolor=color.black)')
    if not bundle.get('annotations'):lines.append('    na')
    return '\n'.join(lines)+'\n'

def mt5_tsv(bundle):
    """Only exact broker-scoped observations can enter the MT5 local channel."""
    scope=bundle['scope']
    if not scope['venue'].startswith('mt5:') or not scope['account_scope'].startswith('mt5-'):raise ValueError('MT5 requires an exact native broker/account scope; no futures aliases')
    if scope['timeframe']!='5m' or scope['mode'] not in ('demo','observe'):raise ValueError('unsupported native timeframe/mode')
    lines=[]
    for a in bundle.get('annotations',[])[:80]:
        x=a['anchors'][0];y=a['anchors'][-1];label=(a.get('assessment') or a.get('signal') or a['role'])+' '+a['strategy_id'];explanation=a['explanation'].replace('\t',' ').replace('\n',' ').replace('\r',' ')
        fields=[a['id'],scope['symbol'],'5',scope['account_scope'],scope['mode'],a['type'],str(int(x['time']+a.get('native_time_offset_seconds',0))),str(x['price']),str(int(y['time']+a.get('native_time_offset_seconds',0))),str(y['price']),a['style']['color'],label,explanation,str(int(a['expires_at']))]
        if any('\t' in s or '\n' in s or '\r' in s for s in fields):raise ValueError('invalid TSV field')
        lines.append('\t'.join(fields))
    header='\t'.join(['NIBLIT_CHART_V1',bundle['chart_key'],str(len(lines)),hashlib.sha256(json.dumps(bundle['annotations'],sort_keys=True).encode()).hexdigest()])
    return header+'\n'+('\n'.join(lines)+'\n' if lines else '')+'END\n'

class ChartView:
    def __init__(self,desk,mt5,core_analysis):
        self.desk=desk;self.mt5=mt5;self.core_analysis=core_analysis;self.lock=threading.Lock();self.cache={};self.clock_receipts={}
    def snapshot(self,environment,symbol,timeframe='5m'):
        if environment not in ('freqtrade','mt5') or timeframe not in ('1m','5m','15m','1h') or (environment=='mt5' and timeframe!='5m'):raise ValueError('unsupported chart environment/timeframe')
        # Revalidate account/mode before serving cached drawings.
        if environment=='freqtrade':
            current=self.desk.configuration();profile=self.desk.root.parent/'freqtrade/user_data/config.json'
            binding=hashlib.sha256((profile.read_bytes() if profile.exists() else b'')+json.dumps(current,sort_keys=True).encode()).hexdigest()
        else:
            _,current_account,_=self.mt5.connect();binding=self.mt5.identity(current_account)+':'+str(getattr(current_account,'trade_mode','unknown'))
        key=(environment,symbol,timeframe,binding)
        with self.lock:
            cached=self.cache.get(key)
            if cached and time.monotonic()-cached[0]<15:return cached[1]
            position=None;native=None
            if environment=='freqtrade':
                config=current
                if symbol not in self.desk.api('whitelist').get('whitelist',[]):raise ValueError('chart requires an exact whitelisted pair')
                market=self.desk.market(symbol,config) if timeframe==config.get('timeframe') else self.desk.public_market(symbol,{**config,'timeframe':timeframe})
                profile=self.desk.root.parent/'freqtrade/user_data/config.json'
                mode='dry-run' if config.get('dry_run') is True else 'observe'
                from modules.position_intelligence import digest
                account='freqtrade-profile-'+digest([str(self.desk.root.resolve()),config.get('exchange'),mode,hashlib.sha256(profile.read_bytes()).hexdigest() if profile.exists() else 'missing_profile'])
                observation={'symbol':symbol,'venue':config['exchange'],'timeframe':timeframe,'mode':mode,'account_scope':account,
                    'source':market.get('source','unavailable'),'received_at':time.time(),'fresh':market.get('fresh') is True,'candles':market.get('candles',[])}
                try:
                    import httpx
                    with httpx.Client(trust_env=False,timeout=5) as c:
                        r=c.get('http://127.0.0.1:5000/api/trading/positions');r.raise_for_status();reports=r.json()
                    actual={p['trade_id']:p for p in self.desk.api('status')}
                    position=next((p for p in reports.get('positions',[]) if p.get('recorded',{}).get('pair')==symbol and p.get('scope',{}).get('account_scope')==account and p['recorded'].get('trade_id') in actual and all(p['recorded'].get(k)==actual[p['recorded']['trade_id']].get(k) for k in ('open_rate','amount','is_short','is_open'))),None)
                    if position:observation['position_intelligence']=position
                except Exception:pass # Position annotation unavailable; market evaluation stays operational.
            else:
                native=self.mt5.snapshot(symbol)
                if not native.get('connected'):raise ValueError('MT5 market unavailable')
                if native['account']['identity']!=self.mt5.identity(current_account):raise ValueError('MT5 account changed during chart capture')
                market={'candles':native['candles'],'fresh':native['quote'].get('fresh') is True,'source':'mt5_broker_completed_bars'}
                clock=self.native_clock(native)
                normalized=[{**c,'timestamp':c['timestamp']-clock['offset_seconds']} for c in native['candles']] if clock.get('verified') else native['candles']
                market={**market,'candles':normalized,'fresh':market['fresh'] and clock.get('verified',False),'time_mapping':clock}
                observation={'symbol':native['symbol'],'venue':'mt5:'+native['account']['server'],'timeframe':timeframe,
                    'mode':'demo' if native['account']['mode']=='demo' else 'observe','account_scope':'mt5-'+native['account']['identity'],
                    'source':market['source'],'received_at':time.time(),'fresh':market['fresh'],'candles':normalized,'native_time_offset_seconds':clock.get('offset_seconds',0),'time_mapping':clock}
            if environment=='mt5' and not market.get('time_mapping',{}).get('verified'):
                result={'environment':environment,'symbol':symbol,'timeframe':timeframe,'market':market,
                        'annotations':{'state':'native_time_mapping_unverified','annotations':[],'execution_authorized':False},
                        'execution_authorized':False,'native_sync':{'state':'waiting_for_clock_receipts'}}
                self.cache[key]=(time.monotonic(),result);return result
            response=self.core_analysis(observation)
            bundle=response.get('annotations') or {'state':'core_unavailable','annotations':[],'execution_authorized':False}
            result={'environment':environment,'symbol':symbol,'timeframe':timeframe,'market':market,'annotations':bundle,
                'core':{k:response.get(k) for k in ('state','authorization','trace_id')},'position':position,
                'execution_authorized':False,'native_sync':{'state':'not_applicable'}}
            if environment=='freqtrade' and bundle.get('chart_key'):
                try:
                    folder=self.desk.root.parent/'freqtrade/user_data/niblit_chart_annotations';folder.mkdir(parents=True,exist_ok=True)
                    path=folder/(hashlib.sha256((symbol+'|'+timeframe).encode()).hexdigest()+'.json')
                    payload={'schema':'niblit.frequi.v1','scope':bundle['scope'],'expires_at':bundle['expires_at'],
                             'profile_sha256':hashlib.sha256(profile.read_bytes()).hexdigest(),
                             'annotations':freqtrade_annotations(bundle),'canonical_ids':[a['id'] for a in bundle['annotations']],'canonical_revisions':[a['revision'] for a in bundle['annotations']],'source_observation_id':bundle.get('observation_id'),'core_trace_id':response.get('trace_id'),'core_authorization':response.get('authorization'),
                             'execution_authorized':False}
                    content=json.dumps(payload,sort_keys=True)
                    if not path.exists() or path.read_text(encoding='utf-8')!=content:
                        temp=path.with_suffix('.tmp');temp.write_text(content,encoding='utf-8');temp.replace(path)
                    result['freqtrade_export']={'state':'snapshot_staged','callback':'NiblitLabManager.plot_annotations'}
                except Exception as exc:result['freqtrade_export']={'state':'pending','error_type':type(exc).__name__}
            if native and bundle.get('chart_key'):
                try:
                    _,account,terminal=self.mt5.connect()
                    if 'mt5-'+self.mt5.identity(account)!=bundle['scope']['account_scope']:raise ValueError('account changed')
                    folder=Path(terminal.commondata_path)/'Files/NiblitCharts';folder.mkdir(parents=True,exist_ok=True)
                    path=folder/(self.safe_symbol(native['symbol'])+'_'+bundle['scope']['account_scope']+'_5m.tsv');content=mt5_tsv(bundle)
                    temp=path.with_suffix('.tmp');temp.write_text(content,encoding='utf-8');temp.replace(path)
                    result['native_sync']={'state':'snapshot_published_not_render_verified','file':path.name,'indicator':'NiblitChartObjects','broker_clock':'UTC anchors converted back using verified contemporaneous native clock receipts'}
                except Exception as exc:result['native_sync']={'state':'pending','error_type':type(exc).__name__}
            if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(time.monotonic(),result)
            return result

    @staticmethod
    def safe_symbol(symbol):return symbol.replace('/','_').replace('\\','_').replace(':','_')
    def native_clock(self,native):
        result={'verified':False,'reason':'Awaiting two native indicator clock receipts; no guessed broker timezone'}
        try:
            _,account,terminal=self.mt5.connect();scope='mt5-'+self.mt5.identity(account)
            if scope!='mt5-'+native['account']['identity']:raise ValueError('account changed')
            path=Path(terminal.commondata_path)/'Files/NiblitCharts'/('clock_'+self.safe_symbol(native['symbol'])+'_'+scope+'.tsv')
            fields=path.read_text(encoding='utf-8-sig').strip().split('\t')
            if len(fields)!=6 or fields[:3]!=['NIBLIT_CLOCK_V1',native['symbol'],scope]:raise ValueError('clock identity mismatch')
            server,utc,last=[int(v) for v in fields[3:]];offset=round((server-utc)/60)*60
            if not 0<=time.time()-utc<=20 or abs(offset)>50400 or abs(server-utc-offset)>2 or abs(server-last)>60:raise ValueError('clock stale or inconsistent')
            key=(scope,native['symbol']);prior=self.clock_receipts.get(key)
            if prior and prior['offset_seconds']==offset and utc-prior['utc']>=5:
                return {'verified':True,'offset_seconds':offset,'server':server,'utc':utc,'previous_utc':prior['utc'],'basis':'Two fresh local MQL TimeTradeServer/TimeGMT receipts; contemporaneous offset, not historical timezone proof'}
            self.clock_receipts[key]={'offset_seconds':offset,'utc':utc}
            return {**result,'offset_seconds':offset}
        except Exception as exc:return {**result,'error_type':type(exc).__name__}
