"""Existing catalog analysis/protections with Core-only bounded entries."""

from NiblitLabManager import NiblitLabManager

from niblit_lab.core_claim import confirm_core_entry





class NiblitCoreManaged(NiblitLabManager):
    position_adjustment_enable=False

    def ft_bot_start(self,**kwargs):
        # This entrypoint is outside Freqtrade's permissive callback wrapper.
        # Refuse a funded profile or position adjustments before the bot starts.
        from freqtrade.exceptions import OperationalException
        if self.config.get('dry_run') is not True or self.config.get('position_adjustment_enable',False) or self.position_adjustment_enable:
            raise OperationalException('This release requires dry-run Core-managed trading with position adjustment disabled')
        return super().ft_bot_start(**kwargs)


    def populate_entry_trend(self,dataframe,metadata):

        dataframe['enter_long']=0

        dataframe['enter_short']=0

        dataframe['enter_tag']=None

        return dataframe



    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):

        return confirm_core_entry(self.config,self.stoploss,self.minimal_roi,

            pair=pair,side=side,amount=amount,rate=rate,entry_tag=entry_tag)



    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):

        try:

            limit=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)

            stake=min(float(proposed_stake),float(limit))

            return stake if stake>0 and (min_stake is None or stake>=min_stake) else 0.

        except Exception:return 0.
