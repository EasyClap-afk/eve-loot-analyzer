from decimal import Decimal as D, ROUND_CEILING
from .rules import decimal, broker, FACILITY_TAX, SCC, ALPHA_SURCHARGE
from .market import purchase, eligible

def material_quantity(base, runs, me):
    return max(runs, int((D(base)*runs*(1-D(me)/100)).to_integral_value(rounding=ROUND_CEILING)))

def job_fee(materials, runs, adjusted, sci, alpha=False):
    if sci is None or any(adjusted.get(m['typeID']) is None for m in materials):
        return None,None
    eiv = sum((D(m['quantity'])*runs*decimal(adjusted[m['typeID']]) for m in materials), D(0))
    return eiv, eiv*(decimal(sci)+FACILITY_TAX+SCC+(ALPHA_SURCHARGE if alpha else 0))

def analyze_blueprint(item, recipe, params, profile, market_fn, orders_fn, adjusted, sci, distances, name_fn):
    result = {**item,'params':params,'materials':[],'outputs':[],'warnings':[], 'build_value':None}
    if not recipe or not recipe.get('products'):
        return {**result,'verdict':'UNSUPPORTED BLUEPRINT','warnings':['No manufacturing activity in SDE.']}
    runs, me, te = (int(params.get(k,d)) for k,d in [('runs',1),('me',0),('te',0)])
    remaining = int(params.get('remaining_runs',runs))
    if not 1<=runs<=remaining or not 0<=me<=10 or not 0<=te<=20:
        raise ValueError('BPC: runs must be 1..remaining runs, ME 0..10, TE 0..20')
    copies = item['quantity']
    # Each copied blueprint is a separate job: round per job, then multiply by copies.
    for m in recipe.get('materials',[]):
        type_id = m['typeID']
        required = material_quantity(m['quantity'], runs, me)*copies
        row = {'type_id':type_id,'name':name_fn(type_id),'quantity':required}
        try:
            orders = orders_fn(type_id)
            if profile.get('material_mode','instant') == 'instant':
                from .rules import STATION
                row.update(purchase([o for o in orders if not o['is_buy_order'] and o['location_id']==STATION],required))
            else:
                best = max((decimal(o['price']) for o in orders if eligible(o,distances)),default=None)
                row.update(cost=best*required*(1+broker(profile)) if best is not None else None,remaining=0 if best is not None else required,
                           note='Own buy order estimate; includes broker fee, fill not guaranteed.')
        except Exception as exc:
            row.update(cost=None,remaining=required,error=str(exc))
        result['materials'].append(row)
    for product in recipe['products']:
        result['outputs'].append(market_fn(product['typeID'],product['quantity']*runs*copies))
    material_cost = sum((r['cost'] for r in result['materials']),D(0)) if all(r['cost'] is not None for r in result['materials']) else None
    eiv, fee = job_fee(recipe.get('materials',[]),runs*copies,adjusted,sci,profile.get('clone')=='Alpha')
    cost = material_cost+fee if material_cost is not None and fee is not None else None
    missing = [{'type_id':s['typeID'],'name':name_fn(s['typeID']),'required':s['level'],
                'current':int(profile.get('skills',{}).get(str(s['typeID']),0))}
               for s in recipe.get('skills',[]) if int(profile.get('skills',{}).get(str(s['typeID']),0))<s['level']]
    result.update(material_cost=material_cost,eiv=eiv,job_fee=fee,build_cost=cost,sci=sci,
                  missing_adjusted=[m['typeID'] for m in recipe.get('materials',[]) if adjusted.get(m['typeID']) is None],
                  missing_skills=missing,can_manufacture=not missing,
                  time_seconds=D(recipe['time'])*runs*(1-D(te)/100)*(1-D('.04')*int(profile.get('industry',0)))*(1-D('.03')*int(profile.get('advanced_industry',0))),
                  jobs=copies,max_jobs=1+int(profile.get('mass_production',0))+int(profile.get('advanced_mass_production',0)))
    for mode in ('instant','sell','realistic'):
        key = mode+'_net'
        outputs = result['outputs']
        value = sum((o[key] for o in outputs),D(0)) if all(o.get(key) is not None and (mode!='instant' or not o.get('unsold')) for o in outputs) else None
        profit = value-cost if value is not None and cost is not None else None
        result['output_'+key] = value
        result[mode+'_profit'] = profit
        result[mode+'_roi'] = profit/cost if profit is not None and cost else None
    profit = result['realistic_profit']
    result['build_value'] = max(D(0),profit) if profit is not None else None
    liquidity = min(o.get('liquidity',0) for o in result['outputs'])
    confidence = min(o.get('confidence',0) for o in result['outputs'])
    result.update(liquidity=liquidity,confidence=confidence)
    if missing: verdict = 'CANNOT BUILD'
    elif cost is None or profit is None: verdict = 'INCOMPLETE DATA'
    elif confidence<45: verdict = 'PRICE UNCERTAIN'
    elif profit<=0: verdict = 'DO NOT BUILD'
    elif liquidity<45: verdict = 'BUILD — LOW LIQUIDITY'
    elif result['realistic_roi']>=D('.15'): verdict = 'BUILD — STRONG'
    else: verdict = 'BUILD — PROFITABLE'
    result['verdict'] = verdict
    if material_cost is None: result['warnings'].append('Material depth incomplete; full build cost N/A.')
    if fee is None: result['warnings'].append('Job fee incomplete: missing SCI or adjusted prices.')
    result['warnings'].append('100% of materials purchased independently; loot is never consumed. Time shown per copy/job.')
    return result
