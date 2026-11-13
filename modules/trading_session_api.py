"""Local operator routes for Core's bounded trading sessions; no model tools."""
import secrets
from typing import Literal
from fastapi import Request,HTTPException
from pydantic import BaseModel,Field


class Proposal(BaseModel):
    model_config={'extra':'forbid'}
    adapter:Literal['mt5','freqtrade','exness_demo']
    symbol:str=Field(min_length=1,max_length=80)
    seconds:int=Field(default=1800,ge=60,le=3600)
    limits:dict[str,float]=Field(default_factory=dict)
    close_order_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')


class Activation(BaseModel):
    model_config={'extra':'forbid'}
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    spec_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    acknowledgement:Literal['ACTIVATE_BOUNDED_DEMO_SESSION']
    clear_emergency_stop:bool=False


class Stop(BaseModel):
    model_config={'extra':'forbid'}
    id:str|None=None
    emergency:bool=False


class NativeReceipt(BaseModel):
    model_config={'extra':'forbid'}
    ticket:str=Field(pattern=r'^[A-Za-z0-9_-]{32}$')
    symbol:str=Field(min_length=1,max_length=80)
    side:Literal['long','short']
    amount:float=Field(gt=0,allow_inf_nan=False)
    rate:float=Field(gt=0,allow_inf_nan=False)
    stoploss:float=Field(lt=0,ge=-.01,allow_inf_nan=False)
    minimal_roi:dict
    fee:float=Field(ge=0,le=.01,allow_inf_nan=False)
    account_binding:str=Field(pattern=r'^[a-f0-9]{64}$')


def register_trading_routes(app,provider):
    allowed={'http://127.0.0.1:5000','http://localhost:5000','http://127.0.0.1:8767',
             'http://localhost:8767','http://127.0.0.1:5173','http://localhost:5173',
             'tauri://localhost','http://tauri.localhost','https://tauri.localhost'}
    def service(request,mutation=False):
        origin=request.headers.get('origin')
        if request.headers.get('host','') not in ('127.0.0.1:5000','localhost:5000','testserver') or (origin is not None and origin not in allowed):
            raise HTTPException(403,'Local Core operator UI required')
        control=provider()
        if control is None:raise HTTPException(503,'Canonical trading control unavailable; execution blocked')
        if mutation and (origin not in allowed or not secrets.compare_digest(request.headers.get('x-niblit-trading-nonce',''),control.nonce)):
            raise HTTPException(403,'Explicit human operator session required')
        return control
    def run(fn):
        try:return fn()
        except HTTPException:raise
        except PermissionError as exc:raise HTTPException(403,str(exc))
        except ValueError as exc:raise HTTPException(409,str(exc))
        except Exception:raise HTTPException(503,'Trading dependency unavailable; no automatic retry')
    @app.post('/api/trading/native-entry-receipt')
    def native_receipt(body:NativeReceipt,request:Request):
        # Native bot callback consumes a sending claim; it cannot activate a
        # session or mint permission. It must not require a browser Origin.
        return run(lambda:service(request).native_entry_receipt(body.model_dump()))

    @app.get('/api/trading/sessions')
    def status(request:Request):return run(lambda:service(request).status())
    @app.get('/api/trading/exness-demo/market')
    def demo_market(request:Request,symbol:str='BTCUSDm'):
        def apply():
            control=service(request)
            if 'exness_demo' not in control.adapters:raise PermissionError('Exness demo is not configured')
            return control.adapters['exness_demo'].market(symbol)
        return run(apply)
    @app.post('/api/trading/sessions/observe')
    def observe(body:Proposal,request:Request):
        def apply():
            control=service(request,True);control.observe(body.adapter,body.symbol)
            return {'observation_started':True,'execution_started':False}
        return run(apply)
    @app.post('/api/trading/sessions/propose')
    def propose(body:Proposal,request:Request):
        return run(lambda:service(request,True).propose(body.adapter,body.symbol,body.seconds,body.limits,close_order_id=body.close_order_id))
    @app.post('/api/trading/sessions/activate')
    def activate(body:Activation,request:Request):
        return run(lambda:service(request,True).activate(body.id,body.spec_hash,clear_stop=body.clear_emergency_stop))
    @app.post('/api/trading/sessions/stop')
    def stop(body:Stop,request:Request):
        return run(lambda:service(request,True).stop(body.id,emergency=body.emergency))
    @app.post('/api/trading/sessions/alerts/{ident}/delivered')
    def delivered(ident:str,request:Request):
        return run(lambda:service(request,True).acknowledge_alert(ident) or {'recorded':True})


def register_market_desk(app,factory):
    """Serve the bundled desk on the authoritative Core, without another port."""
    import threading
    class HostedDesk:
        def __init__(self):self.inner=None;self.lock=threading.Lock()
        async def __call__(self,scope,receive,send):
            if self.inner is None:
                with self.lock:
                    if self.inner is None:self.inner=factory()
            await self.inner(scope,receive,send)
        def shutdown(self):
            if self.inner is not None:
                worker=self.inner.state.demo_autotrader;worker.stop()
                if worker.worker:worker.worker.join(timeout=20)
    hosted=HostedDesk();app.mount('/market-desk',hosted)
    return hosted
