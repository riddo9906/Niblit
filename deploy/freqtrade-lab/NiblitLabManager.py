"""Experimental dry-run-only native strategy catalog; no model or paid APIs.

Installed alongside the shared audited rule kernel by install-freqtrade-lab.py.
Never switches a running engine/profile. Stops/ROI use Freqtrade's native engine.
"""
from freqtrade.strategy import IStrategy
import math
import json
from datetime import timedelta
from niblit_lab.strategy_manager import assess
from niblit_lab.demo_strategy import evaluate
from niblit_lab.position_exit_policy import assess_exit


class NiblitLabManager(IStrategy):
    INTERFACE_VERSION=3
    timeframe='5m'
    startup_candle_count=51
    process_only_new_candles=True
    can_short=True
    stoploss=-.01
    minimal_roi={'0':.02}
    use_exit_signal=True
    chosen_strategy='auto'
    exit_policy_version='strategy-aware-exits-v1'

    def order_filled(self, pair, trade, order, current_time, **kwargs):
        if self.config.get('dry_run') is not True or order.ft_order_side!=trade.entry_side or trade.nr_of_successful_entries!=1:return
        tag=(trade.enter_tag or '').split(':')
        if len(tag)!=3 or tag[0]!='niblit_lab':return
        if trade.get_custom_data(key='niblit_exit_context') is not None:return
        dataframe,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        closed=dataframe.loc[dataframe['date']+timedelta(minutes=5)<=current_time].tail(51)
        rows=self.bars(closed)
        if len(rows)<51:return
        price=float(trade.open_rate)
        initial=getattr(trade,'initial_stop_loss',None)
        if not initial:
            if float(trade.leverage or 1)!=1:return
            initial=price*(1.01 if trade.is_short else .99)
        context={'strategy':tag[1],'initial_stop':float(initial),'peak_price_gain':0.,'giveback_checks':0,
            'breakout_level':min(r['low'] for r in rows[-21:-1]) if trade.is_short else max(r['high'] for r in rows[-21:-1]),
            'policy_version':self.exit_policy_version,'entry_bar':rows[-1]['timestamp']}
        trade.set_custom_data(key='niblit_exit_context',value=context)

    @staticmethod
    def bars(dataframe):
        return [{'timestamp':int(r.date.timestamp()),'open':float(r.open),'high':float(r.high),
                 'low':float(r.low),'close':float(r.close)} for r in dataframe.itertuples()]

    def populate_indicators(self, dataframe, metadata):
        rows=self.bars(dataframe)
        dataframe['lab_direction']='wait'
        dataframe['lab_strategy']='none'
        for i in range(50,len(rows)):
            # Prefixes are essential: never let later backtest rows vote here.
            d=assess(rows[max(0,i-50):i+1],requested=self.chosen_strategy)
            dataframe.loc[dataframe.index[i],'lab_direction']=d['side']
            dataframe.loc[dataframe.index[i],'lab_strategy']=d['strategy']
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        valid=dataframe['volume']>0
        for direction,column in (('buy','enter_long'),('sell','enter_short')):
            mask=valid & (dataframe['lab_direction']==direction)
            dataframe.loc[mask,column]=1
            dataframe.loc[mask,'enter_tag']='niblit_lab:'+dataframe.loc[mask,'lab_strategy']+':'+direction
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe['exit_long']=0
        dataframe['exit_short']=0
        return dataframe

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs):
        # A real config cannot turn this research catalog into funded trading.
        return self.config.get('dry_run') is True and -.01<=self.stoploss<0 and bool(entry_tag and entry_tag.startswith('niblit_lab:'))

    def leverage(self, pair, current_time, current_rate, proposed_leverage, max_leverage, entry_tag, side, **kwargs):
        return 1.

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        if self.config.get('dry_run') is not True or leverage!=1: return 0.
        equity=float(self.wallets.get_total_stake_amount())
        if not math.isfinite(equity) or equity<=0: return 0.
        # 1% native stop + 0.2% cost reserve, 0.25% equity risk budget,
        # 10% notional/equity cap and absolute stake cap of 100.
        stake=min(100.,equity*.1,equity*.0025/.012,float(max_stake))
        return stake if stake>0 and (min_stake is None or stake>=min_stake) else 0.

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if self.config.get('dry_run') is not True:return None
        tag=(trade.enter_tag or '').split(':')
        if len(tag)!=3 or tag[0]!='niblit_lab': return None
        dataframe,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        closed=dataframe.loc[dataframe['date']+timedelta(minutes=5)<=current_time].tail(51)
        rows=self.bars(closed)
        context=trade.get_custom_data(key='niblit_exit_context')
        if context and (not rows or not 300<=current_time.timestamp()-rows[-1]['timestamp']<600):return None
        if context and rows and 300<=current_time.timestamp()-rows[-1]['timestamp']<600 and float(trade.leverage or 1)==1:
            # current_rate is Freqtrade's exit-rate estimate, not a measured
            # bid/ask. A 0.1% spread reserve is disclosed, never relabeled live.
            reserve=float(current_rate)*.001
            position={'type':1 if trade.is_short else 0,'price_open':float(trade.open_rate)}
            quote={'bid':float(current_rate),'ask':float(current_rate),'fresh':True,'timestamp':current_time.timestamp()}
            if trade.is_short:quote['ask']+=reserve
            else:quote['bid']-=reserve
            before=json.dumps(context,sort_keys=True)
            report=assess_exit(position,rows,quote,context)
            report['rate_source']='Freqtrade exit-rate estimate with 0.1% spread reserve; not an observed quote'
            report['engine_profit_ratio']=float(current_profit)
            if json.dumps(context,sort_keys=True)!=before:
                trade.set_custom_data(key='niblit_exit_context',value=context)
            if report['action']=='close':
                reason=report['reason']
                profit_exit=reason.startswith(('Profit protection','Reversion target','RSI reversion'))
                if not profit_exit or current_profit>=.002:
                    trade.set_custom_data(key='niblit_exit_evidence',value=report)
                    return ('niblit_profit_protect' if reason.startswith('Profit protection') else
                            'niblit_failed_breakout' if 'failed breakout' in reason else
                            'niblit_reversion_target' if profit_exit else 'niblit_thesis_invalidated')
        d=evaluate(rows,tag[1])
        opposite='buy' if trade.is_short else 'sell'
        return 'entry_rule_reversed' if d['side']==opposite else None


class NiblitLabTrend(NiblitLabManager): chosen_strategy='trend_v1'
class NiblitLabBreakout(NiblitLabManager): chosen_strategy='breakout_v1'
class NiblitLabRsiRecovery(NiblitLabManager): chosen_strategy='rsi_reversion_v1'
class NiblitLabBollingerRecovery(NiblitLabManager): chosen_strategy='bollinger_reversion_v1'
class NiblitLabEmaPullback(NiblitLabManager): chosen_strategy='ema_pullback_v1'
class NiblitLabSqueezeBreakout(NiblitLabManager): chosen_strategy='squeeze_breakout_v1'
