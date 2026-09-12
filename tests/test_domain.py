from datetime import date,timedelta
from decimal import Decimal as D
import pytest
from app.rules import tax,broker,relist_fee,STATION,SYSTEM
from app.market import eligible,liquidate,purchase,history_metrics,scores,analyze_market,tier
from app.industry import material_quantity,job_fee,analyze_blueprint
from app.parser import parse_loot

TODAY=date(2026,9,9)

def order(price=100,qty=100,buy=True,**kw):
    return dict(price=D(str(price)),volume_remain=qty,is_buy_order=buy,location_id=STATION,
                system_id=SYSTEM,range='station',min_volume=1,order_id=1,issued='2026-01-01',**{}) | kw

def history(volume=100,price=100,days=60):
    return [dict(date=(TODAY-timedelta(days=n)).isoformat(),volume=volume,average=D(price)) for n in range(1,days+1)]

@pytest.mark.parametrize('level,expected',[(0,'0.075'),(5,'0.03375')])
def test_tax(level,expected):assert tax({'accounting':level})==D(expected)

@pytest.mark.parametrize('p,expected',[({},'.03'),({'broker':5},'.015'),({'broker':5,'faction':10,'corporation':10},'.01'),({'broker':0,'faction':-10,'corporation':-10},'.035')])
def test_broker(p,expected):assert broker(p)==D(expected)

def test_relist():
    assert relist_fee(D(100),D(110),{'advanced_broker':5})==D('.96')
    assert relist_fee(D(100),D(90),{})==D('1.35')

@pytest.mark.parametrize('r,loc,system,ok',[('station',STATION,SYSTEM,True),('station',1,SYSTEM,False),('solarsystem',1,SYSTEM,True),('solarsystem',1,7,False),('region',1,7,True),('2',1,7,True),('1',1,7,False),('0',1,SYSTEM,True),('40',1,99,False)])
def test_ranges(r,loc,system,ok):
    assert eligible(order(range=r,location_id=loc,system_id=system),{SYSTEM:0,7:2}) is ok

def test_liquidation_depth_and_minimum():
    r=liquidate([order(100,2),order(90,3,order_id=2)],4)
    assert r['gross']==380 and r['remaining']==0 and len(r['fills'])==2
    r=liquidate([order(100,2)],5)
    assert r['gross']==200 and r['remaining']==3
    assert liquidate([order(100,100,min_volume=10)],9)['gross'] is None
    assert liquidate([order(100,3,min_volume=5)],10)['gross'] is None
    assert liquidate([],1)['gross'] is None
    assert liquidate([order(100,100)],5)['gross']==500

def test_purchase():
    assert purchase([order(100,2),order(110,3)],4)['cost']==420
    assert purchase([order(100,2)],4)=={'cost':None,'partial_cost':D(200),'remaining':2,'fills':[{'order_id':1,'quantity':2,'price':D(100)}]}

def test_station_filter_and_net():
    book=[order(90),order(100,buy=False),order(1,buy=False,location_id=999)]
    r=analyze_market(dict(type_id=1,name='X',quantity=4),book,history(),{}, {SYSTEM:0},TODAY)
    assert r['best_sell']==100 and r['sell_gross']==400 and r['sell_net']==358
    assert r['instant_net']==333
    assert r['stock']==100

@pytest.mark.parametrize('value,points',[(D('.25'),35),(D('.2501'),30),(1,30),(D('1.1'),24),(3,24),(7,16),(14,8),(15,0)])
def test_liquidity_absorption_boundaries(value,points):
    h=history_metrics(history(volume=1),TODAY)
    r=scores(value,1,D(2),D(100),20,h)
    assert r['liquidity_components']['stack']==points

@pytest.mark.parametrize('volume,expected',[(1000,30),(999,24),(100,24),(99,16),(20,16),(19,8),(5,8),(4,2)])
def test_confidence_volume_boundaries(volume,expected):
    h=history_metrics(history(),TODAY);h['volume_30']=volume
    assert scores(1,1,D(2),D(100),20,h)['confidence_components']['volume']==expected

@pytest.mark.parametrize('count,expected',[(20,20),(19,15),(10,15),(9,10),(5,10),(4,5),(2,5),(1,0)])
def test_confidence_depth_boundaries(count,expected):
    h=history_metrics(history(),TODAY)
    assert scores(1,1,D(2),D(100),count,h)['confidence_components']['depth']==expected

def test_history_completed_days_missing_days_and_trends():
    h=history(100,100)+[dict(date=TODAY.isoformat(),volume=100000000,average=D(10000))]
    m=history_metrics(h,TODAY)
    assert m['avg_volume_7']==100 and m['vwap_30']==100 and m['trend_7']==0
    sparse=history_metrics(history(7,100,1),TODAY)
    assert sparse['avg_volume_7']==1 and sparse['observed_days_30']==1

def test_realistic_blend_and_outlier_cap():
    r=analyze_market(dict(type_id=1,name='X',quantity=1),[order(90),order(100,buy=False)],history(),{}, {SYSTEM:0},TODAY)
    assert r['realistic_net']==r['sell_weight']*r['sell_net']+(1-r['sell_weight'])*r['instant_net']
    r=analyze_market(dict(type_id=1,name='X',quantity=1),[order(90),order(1000,1,buy=False)],history(1,100,3),{}, {SYSTEM:0},TODAY)
    assert r['capped'] and r['confidence']<45
    assert r['realistic_net']==r['sell_weight']*D(130)*D('.895')+(1-r['sell_weight'])*r['instant_net']

def test_missing_price_not_zero():
    r=analyze_market(dict(type_id=1,name='X',quantity=1),[],[],{}, {},TODAY)
    assert r['instant_net'] is None and r['sell_net'] is None and r['realistic_net'] is None
    assert r['action']!='SELL TO BUY'

@pytest.mark.parametrize('base,runs,me,expected',[(2,10,10,18),(1,100,10,100),(7,3,6,20),(100,1,0,100)])
def test_me_rounding(base,runs,me,expected):assert material_quantity(base,runs,me)==expected

def test_job_cost():
    mats=[{'typeID':1,'quantity':10}]
    eiv,fee=job_fee(mats,2,{1:D(100)},D('.05'))
    assert eiv==2000 and fee==185
    assert job_fee(mats,2,{1:D(100)},D('.05'),True)[1]==190
    assert job_fee(mats,2,{},D('.05'))==(None,None)

def test_blueprint_economics_and_skills():
    recipe={'materials':[{'typeID':1,'quantity':10}],'products':[{'typeID':2,'quantity':1}],'time':1000,'skills':[{'typeID':3380,'level':1}]}
    profile={'skills':{'3380':1},'industry':1}
    result=analyze_blueprint(dict(type_id=3,name='BP',quantity=1),recipe,dict(runs=2,remaining_runs=2,me=10,te=10),profile,
        lambda t,q:dict(instant_net=D(2000),sell_net=D(2500),realistic_net=D(2200),liquidity=60,confidence=80,unsold=0),
        lambda t:[order(10,100,buy=False)],{1:D(10)},D('.05'),{SYSTEM:0},str)
    assert result['material_cost']==180 and result['job_fee']==D('18.5')
    assert result['build_cost']==D('198.5') and result['realistic_profit']==D('2001.5')
    assert result['realistic_roi']==D('2001.5')/D('198.5')
    assert result['time_seconds']==1728 and result['verdict']=='BUILD — STRONG'
    assert result['missing_skills']==[]

def test_parser_all_formats_and_duplicates():
    index={'tritanium':dict(type_id=34,name='Tritanium',category=4),'some blueprint':dict(type_id=1,name='Some Blueprint',category=9)}
    r=parse_loot('Name\tQuantity\nTritanium\t1,000\tMineral\n12 x Tritanium\n4 Tritanium\nTritanium    2\nSome Blueprint\t1\nUnknown Item\t3\n',index)
    assert r['regular'][0]['quantity']==1018 and len(r['blueprints'])==1 and len(r['unresolved'])==1
    assert parse_loot('0 Tritanium',index)['unresolved']
    assert parse_loot('Tritanium',{'tritanium':dict(type_id=34,name='Tritanium',category=4,ambiguous=True)})['unresolved']

@pytest.mark.parametrize('line',[
    'Some Blueprint\t\tBlueprint Group\t\t0.01 m3',
    'Some Blueprint\t \tBlueprint Group\t0.01 m3',
    'Some Blueprint\t1\tBlueprint Group\t0.01 m3',
    'Some Blueprint\t\t',
])
def test_parser_inventory_blueprint_with_empty_quantity(line):
    index={'some blueprint':dict(type_id=1,name='Some Blueprint',category=9)}
    result=parse_loot(line,index)
    assert result['blueprints'][0]['quantity']==1
    assert result['unresolved']==[]

def test_parser_empty_quantities_duplicates_and_invalid_quantity():
    index={'some blueprint':dict(type_id=1,name='Some Blueprint',category=9)}
    raw='Some Blueprint\t\tBlueprint Group\nSome Blueprint\t3\tBlueprint Group\nSome Blueprint\tinvalid\tBlueprint Group'
    result=parse_loot(raw,index)
    assert result['blueprints'][0]['quantity']==4
    assert len(result['unresolved'])==1
    assert result['unresolved'][0]['suggestions']==['Some Blueprint']

@pytest.mark.parametrize('supply,expected',[(3,25),(4,20),(7,20),(8,15),(14,15),(15,8),(30,8),(31,0)])
def test_liquidity_supply(supply,expected):
    assert scores(1,supply,D(2),D(100),20,history_metrics(history(1),TODAY))['liquidity_components']['supply']==expected

@pytest.mark.parametrize('spread,expected',[(3,20),(4,16),(8,16),(9,12),(15,12),(16,6),(30,6),(31,0)])
def test_liquidity_spread(spread,expected):
    assert scores(1,1,D(spread),D(100),20,history_metrics(history(),TODAY))['liquidity_components']['spread']==expected

@pytest.mark.parametrize('sell,expected',[(105,20),(106,15),(115,15),(116,8),(130,8),(131,0)])
def test_confidence_stability(sell,expected):
    assert scores(1,1,D(2),D(sell),20,history_metrics(history(),TODAY))['confidence_components']['stability']==expected
