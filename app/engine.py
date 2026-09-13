from datetime import datetime, timezone
from decimal import Decimal as D
from .parser import parse_loot
from .market import analyze_market
from .industry import analyze_blueprint
from .rules import SYSTEM
from .storage import dumps
from .cancellation import check_cancelled

class Engine:
    def __init__(self,store,esi):
        self.store,self.esi = store,esi

    def analyze(self, raw, profile, bpc_params=None, progress=lambda s:None):
        check_cancelled()
        if not self.store.meta('sde_build'):
            raise ValueError('Download SDE in Data / Dane before analysis.')
        parsed = parse_loot(raw,self.store.index())
        self.esi.status = {}
        distances = {r['system_id']:r['distance'] for r in self.store.query('SELECT * FROM jumps')}
        order_cache,history_cache,market_cache = {},{},{}
        def orders(type_id):
            check_cancelled()
            if type_id not in order_cache:
                try: order_cache[type_id] = self.esi.orders(type_id)
                except Exception as exc: order_cache[type_id] = exc
            if isinstance(order_cache[type_id],Exception): raise order_cache[type_id]
            return order_cache[type_id]
        def market(type_id,quantity):
            check_cancelled()
            key = (type_id,quantity)
            if key in market_cache: return market_cache[key]
            item = {**self.store.item(type_id),'quantity':quantity}
            errors = []
            try: book = orders(type_id)
            except Exception as exc: book=[]; errors.append('Order book unavailable: '+str(exc))
            try:
                if type_id not in history_cache:
                    try: history_cache[type_id] = self.esi.history(type_id)
                    except Exception as exc: history_cache[type_id] = exc
                if isinstance(history_cache[type_id],Exception):raise history_cache[type_id]
                history = history_cache[type_id]
            except Exception as exc: history=[]; errors.append('History unavailable: '+str(exc))
            result = analyze_market(item,book,history,profile,distances,datetime.now(timezone.utc).date())
            result['warnings'].extend(errors)
            market_cache[key] = result
            return result
        regular = []
        for item in parsed['regular']:
            check_cancelled()
            progress('Analyzing '+item['name'])
            regular.append(market(item['type_id'],item['quantity']))
        adjusted,sci,global_errors = {},None,[]
        if parsed['blueprints']:
            check_cancelled()
            try:
                adjusted = {r['type_id']:r.get('adjusted_price') for r in self.esi.get('/markets/prices',ttl=3600)[0]}
                systems = self.esi.get('/industry/systems',ttl=3600)[0]
                sci = next(a['cost_index'] for r in systems if r['solar_system_id']==SYSTEM for a in r['cost_indices'] if a['activity']=='manufacturing')
            except Exception as exc: global_errors.append('Industry data incomplete: '+str(exc))
        blueprints = []
        for item in parsed['blueprints']:
            check_cancelled()
            progress('Blueprint '+item['name'])
            params = (bpc_params or {}).get(str(item['type_id']),dict(runs=1,me=0,te=0,remaining_runs=1))
            blueprints.append(analyze_blueprint(item,self.store.recipe(item['type_id']),params,profile,market,orders,adjusted,sci,distances,lambda i:self.store.item(i)['name']))
        check_cancelled()
        totals = {}
        for mode in ('instant','sell','realistic'):
            vals = [r[mode+'_net'] for r in regular]
            totals[mode+'_net'] = sum((v for v in vals if v is not None),D(0))
            totals[mode+'_missing'] = sum(v is None for v in vals)
        totals['blueprint_value'] = sum((r['build_value'] for r in blueprints if r['build_value'] is not None),D(0))
        totals['blueprint_missing'] = sum(r['build_value'] is None for r in blueprints)
        totals['estimated_total'] = totals['realistic_net']+totals['blueprint_value']
        totals['partial'] = bool(parsed['unresolved'] or totals['realistic_missing'] or totals['blueprint_missing'] or any(r['unsold'] for r in regular)
            or any(o.get('unsold') for b in blueprints for o in b['outputs']))
        actions = {}
        for r in regular:
            key = r['action']
            actions[key] = actions.get(key,D(0))+(r['instant_net'] if key=='SELL TO BUY' else r['realistic_net'] or D(0))
        return {'regular':regular,'blueprints':blueprints,'unresolved':parsed['unresolved'],'totals':totals,'actions':actions,
                'profile':profile,'raw':raw,'timestamp':datetime.now(timezone.utc).isoformat(),'sde_build':self.store.meta('sde_build'),
                'sources':list(self.esi.status.values()),'warnings':global_errors}

    def refresh_watchlist(self,profile,progress=lambda s:None):
        rows = self.store.query('SELECT * FROM watchlist ORDER BY name')
        if not rows: return []
        report = self.analyze('\n'.join(r['name'] for r in rows),profile,progress=progress)
        found = {r['type_id']:r for r in report['regular']}
        for row in rows:
            result = found.get(row['type_id'])
            if not result: continue
            value = result[{'Sell price':'best_sell','Buy price':'best_buy','Realistic net':'realistic_net'}[row['mode']]]
            self.store.execute('UPDATE watchlist SET last_value=current_value,current_value=?,snapshot=? WHERE type_id=?',
                (str(value) if value is not None else None,dumps({**result,'sources':report['sources']}),row['type_id']))
        return self.store.query('SELECT * FROM watchlist ORDER BY name')
