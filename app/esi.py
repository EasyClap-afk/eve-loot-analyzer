import json
import logging
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
import httpx
from .rules import compatibility_date, REGION
from .storage import dumps

class Esi:
    def __init__(self, store):
        self.store = store
        self.status = {}
        self.client = httpx.Client(base_url='https://esi.evetech.net', timeout=30, headers={
            'User-Agent':'EveLootAnalyzer/1.0 (desktop, local-first)', 'X-Compatibility-Date':compatibility_date()})
        self.blocked_until = 0

    def get(self, path, params=None, ttl=300):
        key = path+'?'+str(sorted((params or {}).items()))
        rows = self.store.query('SELECT * FROM cache WHERE key=?',(key,))
        cached = rows[0] if rows else None
        now = time.time()
        def use_cache(stale=False, error=None):
            self.status[key] = {'source':path,'fetched_at':cached['fetched'], 'stale':stale,'error':error}
            return json.loads(cached['body'], parse_float=__import__('decimal').Decimal), json.loads(cached['headers'])
        if cached and cached['expires']>now:
            return use_cache()
        try:
            if now<self.blocked_until:
                raise RuntimeError('ESI rate limit: retry after cooldown')
            response = self.client.get(path, params=params, headers={'If-None-Match':cached['etag']} if cached and cached['etag'] else {})
            if response.status_code in (420,429,503):
                retry = response.headers.get('Retry-After','60')
                try: delay = float(retry)
                except ValueError:
                    try: delay = parsedate_to_datetime(retry).timestamp()-now
                    except (ValueError,TypeError): delay = 60
                self.blocked_until = now+max(1,delay)
            if int(response.headers.get('X-Esi-Error-Limit-Remain','100'))<5:
                self.blocked_until = now+int(response.headers.get('X-Esi-Error-Limit-Reset','60'))
            expires = now+ttl
            if response.headers.get('Expires'):
                expires = max(now+1,parsedate_to_datetime(response.headers['Expires']).replace(tzinfo=timezone.utc).timestamp())
            if response.status_code == 304 and cached:
                self.store.execute('UPDATE cache SET expires=?,fetched=? WHERE key=?',(expires,now,key))
                cached['fetched'] = now
                return use_cache()
            response.raise_for_status()
            body = response.text
            value = json.loads(body, parse_float=__import__('decimal').Decimal)
            headers = dict(response.headers)
            self.store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?,?)',
                (key,body,response.headers.get('ETag'),now,expires,dumps(headers)))
            self.status[key] = {'source':path,'fetched_at':now,'stale':False,'error':None}
            return value,headers
        except Exception as exc:
            logging.warning('Public ESI request failed: %s: %s',path,exc)
            if cached:
                return use_cache(True,str(exc))
            self.status[key] = {'source':path,'fetched_at':None,'stale':True,'error':str(exc)}
            raise

    def orders(self, type_id):
        params = {'order_type':'all','type_id':type_id,'page':1}
        first,headers = self.get(f'/markets/{REGION}/orders',params)
        result = list(first)
        for page in range(2,int(headers.get('x-pages','1'))+1):
            params['page'] = page
            data,_ = self.get(f'/markets/{REGION}/orders',params)
            result.extend(data)
        return result

    def history(self,type_id):
        return self.get(f'/markets/{REGION}/history',{'type_id':type_id},ttl=3600)[0]

    def close(self):
        self.client.close()
