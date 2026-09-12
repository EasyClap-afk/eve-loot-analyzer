from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal as D
from .rules import SYSTEM, STATION, decimal, tax, broker

def eligible(order, distances):
    if not order.get('is_buy_order') or order.get('volume_remain', 0) <= 0:
        return False
    r = str(order.get('range', 'station'))
    if r == 'station':
        return order['location_id'] == STATION
    if r == 'solarsystem':
        return order['system_id'] == SYSTEM
    if r == 'region':
        return True
    return r.isdigit() and distances.get(order['system_id'], 10**9) <= int(r)

def liquidate(orders, quantity):
    remaining, gross, fills = quantity, D(0), []
    for o in sorted(orders, key=lambda o: (-decimal(o['price']), o.get('issued', ''), o.get('order_id', 0))):
        fill = min(remaining, o['volume_remain'])
        if fill <= 0 or fill < o.get('min_volume', 1):
            continue
        gross += fill * decimal(o['price'])
        fills.append({'order_id': o.get('order_id'), 'quantity': fill, 'price': decimal(o['price'])})
        remaining -= fill
    return {'gross': gross if fills else None, 'remaining': remaining, 'fills': fills}

def purchase(orders, quantity):
    remaining, total, fills = quantity, D(0), []
    for o in sorted(orders, key=lambda x: decimal(x['price'])):
        n = min(remaining, o['volume_remain'])
        if n <= 0:
            continue
        total += n * decimal(o['price'])
        fills.append({'order_id': o.get('order_id'), 'quantity': n, 'price': decimal(o['price'])})
        remaining -= n
    return {'cost': total if remaining == 0 else None, 'partial_cost': total, 'remaining': remaining, 'fills': fills}

def tier(value, thresholds, default=0):
    return next((score for limit, score in thresholds if value <= limit), default)

def history_metrics(history, today=None):
    today = today or date.today()
    days = {date.fromisoformat(h['date']): h for h in history if date.fromisoformat(h['date']) < today}
    def window(n, offset=0):
        return [h for d, h in days.items() if today-timedelta(days=n+offset) <= d < today-timedelta(days=offset)]
    def vwap(rows):
        vol = sum(h['volume'] for h in rows)
        return sum((decimal(h['average'])*h['volume'] for h in rows), D(0))/vol if vol else None
    result = {}
    for n in (7, 30):
        rows = window(n)
        # Missing calendar days count as zero volume; no invented price observations.
        volume = sum(h['volume'] for h in rows)
        current, previous = vwap(rows), vwap(window(n, n))
        result.update({f'volume_{n}': volume, f'avg_volume_{n}': D(volume)/n,
                       f'vwap_{n}': current, f'trend_{n}': current/previous-1 if current is not None and previous else None,
                       f'traded_days_{n}': sum(h['volume'] > 0 for h in rows), f'observed_days_{n}': len(rows)})
    return result

def scores(quantity, stock, spread, sell, count, h):
    infinity = D('Infinity')
    avg = h['avg_volume_7']
    stack_days, supply = (D(quantity)/avg, D(stock)/avg) if avg else (infinity, infinity)
    parts = {'stack': tier(stack_days, [(.25,35),(1,30),(3,24),(7,16),(14,8)]),
             'supply': tier(supply, [(3,25),(7,20),(14,15),(30,8)]),
             'spread': tier(spread if spread is not None else infinity, [(3,20),(8,16),(15,12),(30,6)]),
             'regularity': D(h['traded_days_30'])/30*20}
    liquidity = min(100, int(sum(parts.values())))
    volume = h['volume_30']
    deviation = abs(sell-h['vwap_30'])/h['vwap_30'] if sell is not None and h['vwap_30'] else infinity
    cp = {'traded_days': h['traded_days_30'],
          'volume': next((points for minimum,points in [(1000,30),(100,24),(20,16),(5,8)] if volume >= minimum), 2),
          'depth': next((points for minimum,points in [(20,20),(10,15),(5,10),(2,5)] if count >= minimum),0),
          'stability': tier(deviation, [(D('.05'),20),(D('.15'),15),(D('.30'),8)])}
    confidence = min(100, int(sum(cp.values())))
    label = next((label for minimum,label in [(80,'VERY HIGH'),(65,'HIGH'),(45,'MEDIUM'),(25,'LOW')] if liquidity >= minimum),'VERY LOW')
    clabel = 'HIGH' if confidence >= 75 else 'MEDIUM' if confidence >= 45 else 'LOW'
    eta = tier(stack_days, [(.25,'Likely same day'),(1,'~0–1 day'),(3,'~1–3 days'),(7,'~3–7 days'),(14,'~1–2 weeks')], 'Slow / >2 weeks')
    return dict(liquidity=liquidity, liquidity_label=label, confidence=confidence, confidence_label=clabel,
                liquidity_components=parts, confidence_components=cp, stack_days=stack_days, days_supply=supply,
                eta=eta if confidence >=45 else 'Uncertain / insufficient market history')

def analyze_market(item, orders, history, profile, distances, today=None):
    quantity = item['quantity']
    buys = [o for o in orders if eligible(o, distances)]
    sells = [o for o in orders if not o['is_buy_order'] and o['location_id']==STATION and o['volume_remain']>0]
    best_buy = max((decimal(o['price']) for o in buys), default=None)
    best_sell = min((decimal(o['price']) for o in sells), default=None)
    price = best_sell * (1 + decimal(profile.get('price_offset',0))/100) if best_sell is not None else None
    fill = liquidate(buys, quantity)
    instant = fill['gross'] * (1-tax(profile)) if fill['gross'] is not None else None
    sell_gross = price * quantity if price is not None else None
    sell_net = sell_gross * (1-tax(profile)-broker(profile)) if sell_gross is not None else None
    spread = (best_sell-best_buy)/best_sell*100 if best_sell and best_buy is not None else None
    stock = sum(o['volume_remain'] for o in sells)
    h = history_metrics(history, today)
    sc = scores(quantity, stock, spread, best_sell, len(sells), h)
    weight = next((D(w) for minimum,w in [(80,'.85'),(65,'.75'),(45,'.60'),(25,'.40')] if sc['liquidity'] >= minimum),D('.20'))
    sell_component, capped = sell_net, False
    if sc['confidence'] <45 and h['vwap_30'] and price and price > D('1.30')*h['vwap_30']:
        sell_component = D('1.30')*h['vwap_30']*quantity*(1-tax(profile)-broker(profile))
        capped = True
    # Blend only known scenarios. Partial buy proceeds explicitly exclude unsold units.
    realistic = weight*sell_component+(1-weight)*instant if sell_component is not None and instant is not None else None
    warnings = []
    if fill['remaining']: warnings.append(f'Insufficient buy depth: {fill["remaining"]} unsold')
    if instant is None: warnings.append('Instant Sell N/A — no executable buy order')
    if sell_net is None: warnings.append('Sell Order N/A — no Jita 4-4 sell order')
    if realistic is None: warnings.append('Realistic N/A — one or both market scenarios unavailable')
    if capped: warnings.append('Realistic sell component capped at 130% of The Forge VWAP30')
    if h['observed_days_30'] <30: warnings.append(f'Incomplete history: {h["observed_days_30"]}/30 days')
    if sc['confidence'] <45:
        action,reason = 'PRICE UNRELIABLE','Confidence below 45; review history and depth.'
    elif sc['liquidity'] <25 or h['avg_volume_30'] <D('.1'):
        action,reason = 'LOW LIQUIDITY','Low volume or liquidity below 25.'
    elif best_sell and h['vwap_30'] and best_sell<h['vwap_30']*D('.8') and h['avg_volume_7']>=h['avg_volume_30']*D('.8'):
        action,reason = 'HOLD / WATCH','Current sell is >20% below VWAP30 with stable volume.'
    elif instant is not None and not fill['remaining'] and spread is not None and spread<=3 and sc['liquidity']>=65:
        action,reason = 'SELL TO BUY','Full depth available, spread ≤3% and liquidity ≥65.'
    elif sell_net is not None and instant is not None and sell_net>=instant*(1+decimal(profile.get('list_margin',5))/100) and sc['liquidity']>=45:
        action,reason = 'LIST ON MARKET','Net premium meets profile threshold and liquidity ≥45.'
    else:
        action,reason = 'HOLD / WATCH','No strong sell signal; review depth and expected wait.'
    levels = defaultdict(int)
    for o in sells: levels[decimal(o['price'])] += o['volume_remain']
    return {**item, **h, **sc, 'best_buy':best_buy, 'best_sell':best_sell, 'listing_price':price,
            'instant_gross':fill['gross'], 'instant_net':instant, 'unsold':fill['remaining'], 'buy_fills':fill['fills'],
            'sell_gross':sell_gross,'sell_net':sell_net,'realistic_net':realistic,'spread':spread,'stock':stock,
            'sell_depth':[{'price':p,'quantity':q} for p,q in sorted(levels.items())[:10]],
            'sell_weight':weight,'capped':capped,'action':action,'reason':reason,'warnings':warnings,
            'sales_tax':tax(profile),'broker_fee':broker(profile),'history_source':'The Forge market history (regional proxy for Jita)'}
