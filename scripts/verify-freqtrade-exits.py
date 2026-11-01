"""Run inside the installed Freqtrade container; synthetic trades, no orders."""
import sys
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pandas as pd

sys.path.insert(0,'/freqtrade/user_data/strategies')
from NiblitLabManager import NiblitLabManager

class TradeFixture(SimpleNamespace):
    def get_custom_data(self,key):return self.data.get(key)
    def set_custom_data(self,key,value):self.data[key]=value

start=datetime(2026,1,1,tzinfo=timezone.utc)
now=start+timedelta(minutes=255,seconds=15)
frame=pd.DataFrame([{'date':start+timedelta(minutes=i*5),'open':100.6,'high':100.7,'low':100.5,'close':100.6,'volume':1} for i in range(51)])
frame.loc[50,['open','high','low','close']]=[101.,101.1,100.9,101.]
strategy=object.__new__(NiblitLabManager)
strategy.config={'dry_run':True}
strategy.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(frame,None))
trade=TradeFixture(data={},enter_tag='niblit_lab:breakout_v1:buy',entry_side='buy',nr_of_successful_entries=1,
                   open_rate=100.,initial_stop_loss=99.,leverage=1.,is_short=False)
order=SimpleNamespace(ft_order_side='buy')
strategy.order_filled('TEST/USDT',trade,order,now)
assert trade.data['niblit_exit_context']['initial_stop']==99
assert strategy.custom_exit('TEST/USDT',trade,now,101.2,.012) is None
peak=trade.data['niblit_exit_context']['peak_price_gain']
strategy.order_filled('TEST/USDT',trade,order,now)
assert trade.data['niblit_exit_context']['peak_price_gain']==peak
assert strategy.custom_exit('TEST/USDT',trade,now+timedelta(seconds=15),100.7,.007) is None
assert strategy.custom_exit('TEST/USDT',trade,now+timedelta(seconds=15),100.7,.007) is None
assert strategy.custom_exit('TEST/USDT',trade,now+timedelta(seconds=30),100.7,.007)=='niblit_profit_protect'
assert trade.data['niblit_exit_evidence']['engine_profit_ratio']==.007
strategy.config={'dry_run':False}
assert strategy.custom_exit('TEST/USDT',trade,now+timedelta(seconds=45),100.7,.007) is None
strategy.config={'dry_run':True}
old=TradeFixture(**{**trade.__dict__,'data':{}})
strategy.custom_exit('TEST/USDT',old,now,100.6,.006)
assert old.data=={}
assert strategy.leverage(None,None,None,9,20,None,None)==1
print('PASS: native callbacks, persistent context, distinct confirmations, profit protection, funded guard, old-trade isolation and leverage cap. No orders sent.')
