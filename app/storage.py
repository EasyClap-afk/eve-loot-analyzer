import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=lambda x: str(x) if isinstance(x, Decimal) else x.isoformat())

def data_dir():
    p = Path(os.environ.get('EVE_LOOT_DATA', Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'EveLootAnalyzer'))
    p.mkdir(parents=True, exist_ok=True)
    return p

class Store:
    def __init__(self, path=None):
        self.path = str(path or data_dir() / 'analyzer.sqlite3')
        with self.connect() as c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS item_types(type_id INTEGER PRIMARY KEY,name TEXT COLLATE NOCASE,group_id INTEGER,category INTEGER,volume TEXT,published INTEGER);
                CREATE TABLE IF NOT EXISTS blueprint_recipes(type_id INTEGER PRIMARY KEY,recipe TEXT);
                CREATE TABLE IF NOT EXISTS jumps(system_id INTEGER PRIMARY KEY,distance INTEGER);
                CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,body TEXT,etag TEXT,fetched REAL,expires REAL,headers TEXT);
                CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY,body TEXT);
                CREATE TABLE IF NOT EXISTS watchlist(type_id INTEGER PRIMARY KEY,name TEXT,mode TEXT,target TEXT,direction TEXT,last_value TEXT,current_value TEXT,snapshot TEXT);
                CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,site TEXT,name TEXT,timestamp TEXT,duration TEXT,pilots INTEGER,raw TEXT,snapshot TEXT);
            ''')
            schema=c.execute("SELECT sql FROM sqlite_master WHERE name='item_types'").fetchone()[0]
            if 'UNIQUE' in schema:
                c.executescript('''ALTER TABLE item_types RENAME TO item_types_old;
                    CREATE TABLE item_types(type_id INTEGER PRIMARY KEY,name TEXT COLLATE NOCASE,group_id INTEGER,category INTEGER,volume TEXT,published INTEGER);
                    INSERT INTO item_types SELECT * FROM item_types_old;
                    DROP TABLE item_types_old;''')
            c.execute('CREATE INDEX IF NOT EXISTS item_name_index ON item_types(name)')
        seed=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets'/'sde.sqlite3'
        if path is None and not self.meta('sde_build') and seed.exists():
            with self.connect() as c:
                c.execute('ATTACH DATABASE ? AS seed',(str(seed),))
                for table in ('item_types','blueprint_recipes','jumps'):
                    c.execute(f'INSERT INTO {table} SELECT * FROM seed.{table}')
                c.execute("INSERT OR REPLACE INTO metadata SELECT * FROM seed.metadata WHERE key='sde_build'")

    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return c

    def query(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as c:
            return c.execute(sql, args).lastrowid

    def meta(self, key, default=None):
        rows = self.query('SELECT value FROM metadata WHERE key=?', (key,))
        return rows[0]['value'] if rows else default

    def set_meta(self, key, value):
        self.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, str(value)))

    def item(self, type_id):
        rows = self.query('SELECT * FROM item_types WHERE type_id=?', (type_id,))
        return rows[0] if rows else dict(type_id=type_id, name=f'Type {type_id}', category=None)

    def index(self):
        index={}
        for r in self.query('SELECT * FROM item_types ORDER BY published DESC,type_id'):
            name=r['name'].casefold()
            if name not in index:index[name]=r
            elif r['published']==index[name]['published']:
                index[name]['ambiguous']=True
        return index

    def recipe(self, type_id):
        rows = self.query('SELECT recipe FROM blueprint_recipes WHERE type_id=?', (type_id,))
        return json.loads(rows[0]['recipe']) if rows else None

    def profile(self, name='Default'):
        rows = self.query('SELECT body FROM profiles WHERE name=?', (name,))
        return json.loads(rows[0]['body']) if rows else {'name': name, 'clone': 'Omega', 'material_mode': 'instant', 'skills': {}}

    def save_profile(self, p):
        self.execute('INSERT OR REPLACE INTO profiles VALUES(?,?)', (p['name'], dumps(p)))
        self.set_meta('active_profile', p['name'])

    def save_session(self, name, site, duration, pilots, raw, snapshot):
        return self.execute('INSERT INTO sessions(site,name,timestamp,duration,pilots,raw,snapshot) VALUES(?,?,?,?,?,?,?)',
                            (site, name, datetime.now(timezone.utc).isoformat(), str(duration) if duration else None, pilots, raw, dumps(snapshot)))

    def sessions(self):
        rows = self.query('SELECT * FROM sessions ORDER BY timestamp DESC')
        for r in rows:
            r['snapshot'] = json.loads(r['snapshot'])
        return rows

    def backup(self, path):
        with self.connect() as source, sqlite3.connect(path) as destination:
            source.backup(destination)
