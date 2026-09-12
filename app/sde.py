import json
import zipfile
from collections import defaultdict, deque
from pathlib import Path
import httpx
from .storage import dumps, data_dir
from .rules import SYSTEM

BASE = 'https://developers.eveonline.com/static-data/tranquility'

def update_sde(store, progress=lambda s:None):
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(BASE+'/latest.jsonl')
        response.raise_for_status()
        build = next(json.loads(line)['buildNumber'] for line in response.text.splitlines() if json.loads(line).get('_key')=='sde')
        if store.meta('sde_build') == str(build):
            progress(f'SDE {build} is current.')
            return str(build)
        path = data_dir()/'sde-download.zip'
        try:
            with client.stream('GET',f'{BASE}/eve-online-static-data-{build}-jsonl.zip') as r, path.open('wb') as f:
                r.raise_for_status()
                size = 0
                for chunk in r.iter_bytes(1024*1024):
                    f.write(chunk)
                    size += len(chunk)
                    progress(f'Downloading SDE: {size//1024//1024} MB')
            import_sde(store,path,build,progress)
        finally:
            path.unlink(missing_ok=True)
    return str(build)

def import_sde(store,path,build,progress=lambda s:None):
    with zipfile.ZipFile(path) as z:
        def records(name):
            filename = next(n for n in z.namelist() if Path(n).name==name+'.jsonl')
            with z.open(filename) as f:
                for line in f:
                    if line.strip(): yield json.loads(line)
        groups = {int(r['_key']):r['categoryID'] for r in records('groups')}
        progress('Importing item names and blueprint recipes…')
        # One transaction: failed imports preserve the complete previous build.
        with store.connect() as c:
            c.execute('DELETE FROM item_types')
            c.execute('DELETE FROM blueprint_recipes')
            count = 0
            for r in records('types'):
                name = r.get('name',{}).get('en')
                if not name: continue
                c.execute('INSERT OR IGNORE INTO item_types VALUES(?,?,?,?,?,?)',
                    (r['_key'],name,r['groupID'],groups.get(r['groupID']),str(r.get('volume',0)),int(r.get('published',False))))
                count += 1
            if count <1000: raise ValueError('Invalid or incomplete SDE type index')
            for r in records('blueprints'):
                c.execute('INSERT INTO blueprint_recipes VALUES(?,?)',(r['_key'],dumps(r.get('activities',{}).get('manufacturing',{}))))
            progress('Building stargate distances from Jita…')
            gates = {int(r['_key']):r for r in records('mapStargates')}
            graph = defaultdict(set)
            for r in gates.values():
                dest = r.get('destination',{})
                target = dest.get('solarSystemID')
                if target is None and dest.get('stargateID') in gates:
                    target = gates[dest['stargateID']]['solarSystemID']
                if target is not None:
                    source = r['solarSystemID']
                    graph[source].add(target)
                    graph[target].add(source)
            distances,queue = {SYSTEM:0},deque([SYSTEM])
            while queue:
                source = queue.popleft()
                for target in graph[source]:
                    if target not in distances:
                        distances[target] = distances[source]+1
                        queue.append(target)
            if len(distances)<1000: raise ValueError('SDE stargate graph is incomplete')
            c.execute('DELETE FROM jumps')
            c.executemany('INSERT INTO jumps VALUES(?,?)',distances.items())
            c.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('sde_build',str(build)))
        progress(f'SDE {build}: {count:,} types, {len(distances):,} systems.')
