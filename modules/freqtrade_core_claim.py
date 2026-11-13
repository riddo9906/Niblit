"""Native Freqtrade confirmation of an already-authorized Core claim.



No permission is granted here. Any error is a denial; the native strategy's

safe-wrapper default must never turn a transport error into an accepted entry.

"""

import json

import math

import re

import hashlib

from urllib.request import Request,build_opener,ProxyHandler





def account_binding(config):

    exchange=config.get('exchange',{})

    values=[exchange.get('name') if isinstance(exchange,dict) else None,

            config.get('stake_currency'),str(config.get('trading_mode','')),config.get('db_url')]

    if not all(isinstance(value,str) and value for value in values):raise ValueError('Explicit native account profile required')

    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()





def core_receipt(body):

    request=Request('http://127.0.0.1:5000/api/trading/native-entry-receipt',

        data=json.dumps(body,allow_nan=False).encode(),headers={'Content-Type':'application/json'})

    with build_opener(ProxyHandler({})).open(request,timeout=5) as response:

        return json.loads(response.read())





def confirm_core_entry(config,stoploss,roi,*,pair,side,amount,rate,entry_tag,verify=None):

    try:

        if config.get('dry_run') is not True or config.get('strategy')!='NiblitCoreManaged' or config.get('position_adjustment_enable',False):return False

        if side not in ('long','short') or (side=='short' and config.get('trading_mode')!='futures'):return False

        if not isinstance(entry_tag,str) or not re.fullmatch(r'niblit_core:[A-Za-z0-9_-]{32}',entry_tag):return False

        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (amount,rate)):return False

        if not isinstance(stoploss,(int,float)) or not -.01<=stoploss<0:return False

        if not isinstance(roi,dict) or not roi or any(not math.isfinite(float(v)) or float(v)<=0 for v in roi.values()):return False

        result=(verify or core_receipt)({'ticket':entry_tag.split(':')[1],'symbol':pair,'side':side,

            'amount':amount,'rate':rate,'stoploss':stoploss,'minimal_roi':{str(k):v for k,v in roi.items()},'fee':config.get('fee'),

            'account_binding':account_binding(config)})

        return isinstance(result,dict) and result.get('allowed') is True

    except Exception:

        return False
