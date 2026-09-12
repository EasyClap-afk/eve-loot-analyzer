import copy
import json
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
import httpx
from app.storage import Store,dumps
from app.engine import Engine
from app.esi import Esi
from app.rules import STATION,SYSTEM

def populate(store):
    with store.connect() as c:
        for i in range(1,8):c.execute('INSERT INTO item_types VALUES(?,?,?,?,?,?)',(i,'Item '+str(i),1,9 if i>5 else 4,'1',1))
        for i in (6,7):c.execute('INSERT INTO blueprint_recipes VALUES(?,?)',(i,dumps({'materials':[{'typeID':1,'quantity':10}],'products':[{'typeID':2,'quantity':1}],'time':1000,'skills':[]})))
        c.execute('INSERT INTO jumps VALUES(?,0)',(SYSTEM,))
    store.set_meta('sde_build','test')

class FakeEsi:
    def __init__(self):self.status={};self.calls={}
    def orders(self,t):
        self.calls[t]=self.calls.get(t,0)+1
        return [dict(price=D(90),volume_remain=10000,is_buy_order=True,location_id=STATION,system_id=SYSTEM,range='station',min_volume=1),dict(price=D(100),volume_remain=10000,is_buy_order=False,location_id=STATION)]
    def history(self,t):
        return [dict(date=(datetime.now(timezone.utc).date()-timedelta(days=i)).isoformat(),volume=1000,average=D(100)) for i in range(1,61)]
    def get(self,path,ttl=0):
        if path=='/markets/prices':return [{'type_id':1,'adjusted_price':D(80)}],{}
        return [{'solar_system_id':SYSTEM,'cost_indices':[{'activity':'manufacturing','cost_index':D('.05')}]}],{}

def test_end_to_end_session_watch_and_no_loot_discount(tmp_path):
    s=Store(tmp_path/'test.db');populate(s);api=FakeEsi();engine=Engine(s,api)
    raw='\n'.join(f'Item {i}\t2' for i in range(1,8))
    p={'accounting':5,'broker':5,'skills':{}}
    r=engine.analyze(raw,p,{'6':dict(runs=1,remaining_runs=1,me=6,te=10)})
    assert len(r['regular'])==5 and len(r['blueprints'])==2 and not r['unresolved']
    assert all(n==1 for n in api.calls.values())
    assert r['blueprints'][0]['material_cost']==2000
    s.save_session('test','World Ark',30,2,raw,r)
    original=s.sessions()[0]['snapshot']['totals']['realistic_net']
    r['totals']['realistic_net']=D(999999999)
    assert s.sessions()[0]['snapshot']['totals']['realistic_net']==original
    s.execute('INSERT INTO watchlist(type_id,name,mode,target,direction) VALUES(?,?,?,?,?)',(1,'Item 1','Sell price','90','>='))
    watched=engine.refresh_watchlist(p)
    assert D(watched[0]['current_value'])==100
    assert watched[0]['last_value'] is None
    assert engine.refresh_watchlist(p)[0]['last_value']=='100'
    s.backup(tmp_path/'backup.db')
    assert len(Store(tmp_path/'backup.db').sessions())==1

def test_cache_etag_pagination_stale_and_no_cache(tmp_path):
    s=Store(tmp_path/'test.db');esi=Esi(s);calls=[]
    def handler(request):
        calls.append(request)
        page=int(request.url.params.get('page','1'))
        if request.headers.get('if-none-match')=='v1':return httpx.Response(304,headers={'Expires':'Wed, 09 Sep 2099 12:00:00 GMT'})
        return httpx.Response(200,json=[{'page':page}],headers={'ETag':'v1','X-Pages':'2'})
    esi.client.close();esi.client=httpx.Client(base_url='https://test',transport=httpx.MockTransport(handler))
    assert esi.orders(1)==[{'page':1},{'page':2}]
    assert len(calls)==2
    esi.orders(1);assert len(calls)==2
    s.execute('UPDATE cache SET expires=0')
    esi.orders(1);assert len(calls)==4 and calls[-1].headers['if-none-match']=='v1'
    s.execute('UPDATE cache SET expires=0')
    esi.client.close();esi.client=httpx.Client(base_url='https://test',transport=httpx.MockTransport(lambda r:httpx.Response(503,headers={'Retry-After':'60'})))
    assert esi.orders(1)==[{'page':1},{'page':2}]
    assert all(x['stale'] for x in esi.status.values())
    import pytest
    with pytest.raises(RuntimeError):esi.orders(2)

def test_profile_roundtrip(tmp_path):
    s=Store(tmp_path/'test.db');p={'name':'Pilot','accounting':5,'faction':'9.123','skills':{'3380':5}}
    s.save_profile(p);assert s.profile('Pilot')==p

def test_inventory_blueprints_empty_quantity_reach_manufacturing(tmp_path):
    s=Store(tmp_path/'blueprints.db');populate(s)
    r=Engine(s,FakeEsi()).analyze('Item 1\t100\tMineral\nItem 6\t\tBlueprint Group\t0.01 m3\nItem 7\t2\tBlueprint Group',{})
    assert not r['unresolved']
    assert [(b['type_id'],b['quantity']) for b in r['blueprints']]==[(6,1),(7,2)]
    assert all(b['outputs'] and b['build_cost'] is not None for b in r['blueprints'])
