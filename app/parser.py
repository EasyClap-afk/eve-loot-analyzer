import re
from collections import defaultdict
from difflib import get_close_matches

def parse_loot(raw, index):
    totals = defaultdict(int)
    unresolved = []
    headers = {'name', 'item', 'item name', 'nazwa', 'quantity', 'name\tquantity', 'item\tquantity'}
    for original in raw.splitlines():
        line = original.strip().replace('\u00a0', ' ')
        if not line or line.casefold() in headers or line.casefold().startswith('name\tquantity\t'):
            continue
        candidates = [(line, '1')]
        # Preserve empty inventory cells: singleton blueprints can have a blank
        # quantity before their group/volume columns. Collapsing tabs shifts the
        # group name into the quantity field and makes a valid type unresolved.
        columns = line.split('\t')
        if len(columns) > 1:
            candidates.insert(0, (columns[0].strip(), columns[1].strip() or '1'))
        m = re.match(r'^([\d, .]+)\s+(?:[x×]\s+)?(.+)$', line)
        if m:
            candidates.append((m[2].strip(), m[1]))
        m = re.match(r'^(.+?)\s+(?:[x×]\s*)?([\d, .]+)$', line)
        if m:
            candidates.append((m[1].strip(), m[2]))
        found = False
        for name, quantity in candidates:
            item = index.get(name.casefold())
            q = re.sub(r'[, .]', '', quantity)
            if item and not item.get('ambiguous') and q.isdigit() and 0 < int(q) <= 10**15:
                totals[item['type_id']] += int(q)
                found = True
                break
        if not found:
            lookup = columns[0].strip() if len(columns)>1 else candidates[-1][0]
            suggestions = get_close_matches(lookup.casefold(), index, n=3, cutoff=.75)
            unresolved.append({'line': original, 'suggestions': [index[n]['name'] for n in suggestions]})
    by_id = {x['type_id']: x for x in index.values()}
    items = [{**by_id[k], 'quantity': q} for k, q in totals.items()]
    return {'regular': [x for x in items if x['category'] != 9],
            'blueprints': [x for x in items if x['category'] == 9], 'unresolved': unresolved}
