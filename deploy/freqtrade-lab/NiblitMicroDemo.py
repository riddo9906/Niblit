"""Staged 1m burst experiment. Disabled without an explicit ten-minute session.

Separate profile/database required. No existing engine is switched by this file.
"""
from datetime import datetime,timezone,timedelta
import math
from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade


class NiblitMicroDemo(IStrategy):
    INTERFACE_VERSION=3
    timeframe='1m'
    startup_candle_count=40
    process_only_new_candles=True
    can_short=False
    stoploss=-.004
    minimal_roi={'0':.003}
    use_exit_signal=True

    def populate_indicators(self,df,metadata):
        df['fast']=df['close'].ewm(span=9,adjust=False).mean()
        df['slow']=df['close'].ewm(span=21,adjust=False).mean()
        return df

    def populate_entry_trend(self,df,metadata):
        condition=(df['volume']>0)&(df['fast']>df['slow'])&(df['close'].shift(1)<=df['fast'].shift(1))&(df['close']>df['fast'])
        df.loc[condition,['enter_long','enter_tag']]=[1,'niblit_micro_v1']
        return df

    def populate_exit_trend(self,df,metadata):
        df.loc[(df['close']<df['fast'])&(df['close'].shift(1)<df['fast'].shift(1)),['exit_long','exit_tag']]=[1,'micro_mean_invalidated']
        return df

    def leverage(self,*args,**kwargs):return 1.

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        if self.config.get('dry_run') is not True or entry_tag!='niblit_micro_v1' or side!='long':return False
        session=self.config.get('niblit_micro_session',{})
        start=session.get('started_at',0)
        if not isinstance(start,(int,float)) or not math.isfinite(start) or not 0<=current_time.timestamp()-start<600:return False
        if Trade.get_open_trade_count()!=0:return False
        history=Trade.get_trades_proxy(is_open=False,open_date=datetime.fromtimestamp(start,timezone.utc))
        if len(history)>=5:return False
        if sum(float(t.close_profit_abs or 0) for t in history)<=-min(2.,float(self.wallets.get_total_stake_amount())*.01):return False
        if any(t.close_date_utc and current_time-t.close_date_utc<timedelta(seconds=45) for t in history):return False
        # Cost gate requires an actual order book; no invented tight spread.
        book=self.dp.orderbook(pair,1)
        bid=float(book['bids'][0][0]);ask=float(book['asks'][0][0])
        return 0<bid<=ask and (ask-bid)/bid<=.0005

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        if self.config.get('dry_run') is not True or leverage!=1:return 0.
        equity=float(self.wallets.get_total_stake_amount())
        if not math.isfinite(equity) or equity<=0:return 0.
        stake=min(10.,equity*.05,equity*.0025/.006,float(max_stake))
        return stake if stake>0 and (min_stake is None or stake>=min_stake) else 0.

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.config.get('dry_run') is not True:return None
        peak=max(float(trade.get_custom_data(key='micro_peak_profit') or 0),float(current_profit))
        trade.set_custom_data(key='micro_peak_profit',value=peak)
        if peak>=.004 and peak-current_profit>=.0015 and current_profit>=.002:return 'micro_profit_giveback'
        if current_time-trade.open_date_utc>=timedelta(minutes=5):return 'micro_time_limit'
        return None
