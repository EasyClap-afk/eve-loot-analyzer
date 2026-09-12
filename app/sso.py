"""Native OAuth PKCE; refresh tokens live only in the OS credential store."""
import base64
import hashlib
import secrets
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
import jwt
import keyring
from .rules import compatibility_date, SKILL_IDS
from .i18n import tr

REDIRECT = 'http://localhost:8765/callback'
SCOPES = 'esi-skills.read_skills.v1 esi-characters.read_standings.v1'
SERVICE = 'EveLootAnalyzer'
# Allow small differences between the Windows and SSO clocks, in seconds.
CLOCK_SKEW_LEEWAY = 60

class SSO:
    def __init__(self):
        self.access = {}

    def disconnect(self, profile):
        key = profile['name']
        try: keyring.delete_password(SERVICE,key)
        except keyring.errors.PasswordDeleteError: pass
        self.access.pop(key,None)
        profile.pop('character_id',None)
        profile.pop('character_name',None)
        return profile

    def connect(self,profile,progress=lambda s:None):
        client_id = profile.get('client_id','').strip()
        if not client_id: raise ValueError('Enter your EVE developer application Client ID in Settings. Callback: '+REDIRECT)
        verifier,state = secrets.token_urlsafe(64),secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        result = {}
        class Callback(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                valid = url.path=='/callback' and secrets.compare_digest(query.get('state',[''])[0],state)
                if not valid:
                    self.send_response(400);self.send_header('Content-Type','text/plain; charset=utf-8');self.end_headers();self.wfile.write(tr('Invalid callback state.').encode('utf-8'));return
                if query.get('error'): result['error'] = query['error'][0]
                elif query.get('code'): result['code'] = query['code'][0]
                else: result['error'] = 'Missing authorization code'
                self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.end_headers();self.wfile.write(tr('You may close this tab and return to EVE Loot Analyzer.').encode('utf-8'))
            def log_message(self,*args): pass
        with HTTPServer(('127.0.0.1',8765),Callback) as server:
            server.timeout = 1
            query = urlencode(dict(response_type='code',redirect_uri=REDIRECT,client_id=client_id,scope=SCOPES,
                                   state=state,code_challenge=challenge,code_challenge_method='S256'))
            webbrowser.open('https://login.eveonline.com/v2/oauth/authorize?'+query)
            progress('SSO: complete login in your browser (timeout 3 minutes).')
            end = time.monotonic()+180
            while not result and time.monotonic()<end: server.handle_request()
        if not result.get('code'): raise ValueError('SSO: '+result.get('error','Login timed out'))
        token = self._token(dict(grant_type='authorization_code',code=result['code'],client_id=client_id,code_verifier=verifier,redirect_uri=REDIRECT))
        claims = self._claims(token['access_token'],client_id)
        profile['character_id'] = int(claims['sub'].split(':')[-1])
        profile['character_name'] = claims.get('name',str(profile['character_id']))
        self._save(profile,token)
        return self.sync(profile)

    def _claims(self,token,client_id):
        with httpx.Client(timeout=30) as c:
            r=c.get('https://login.eveonline.com/.well-known/oauth-authorization-server');r.raise_for_status();metadata=r.json()
        signing = jwt.PyJWKClient(metadata['jwks_uri']).get_signing_key_from_jwt(token)
        try:
            claims = jwt.decode(token,signing.key,algorithms=['RS256'],audience='EVE Online',issuer=metadata['issuer'],
                                leeway=CLOCK_SKEW_LEEWAY,options={'require':['exp','iss','sub','aud']})
        except jwt.ImmatureSignatureError as exc:
            raise ValueError('SSO: czas tokenu wyprzedza zegar komputera o ponad 60 sekund. '
                             'W Windows otwórz Ustawienia → Czas i język → Data i godzina → Synchronizuj teraz, '
                             'a następnie ponownie połącz postać.') from exc
        if claims.get('azp')!=client_id: raise ValueError('SSO client identifier mismatch')
        return claims

    def _token(self,data):
        with httpx.Client(timeout=30) as c:
            r=c.post('https://login.eveonline.com/v2/oauth/token',data=data)
            if r.status_code!=200: raise ValueError(f'SSO token request failed (HTTP {r.status_code}); re-login required.')
            return r.json()

    def _save(self,profile,token):
        if token.get('refresh_token'): keyring.set_password(SERVICE,profile['name'],token['refresh_token'])
        self.access[profile['name']] = (token['access_token'],time.time()+token.get('expires_in',1200)-60)

    def sync(self,profile):
        if not profile.get('character_id'): raise ValueError('Connect a character first.')
        access,expires = self.access.get(profile['name'],(None,0))
        if expires<time.time():
            refresh=keyring.get_password(SERVICE,profile['name'])
            if not refresh: raise ValueError('SSO disconnected / re-login required.')
            token=self._token(dict(grant_type='refresh_token',refresh_token=refresh,client_id=profile['client_id']))
            claims=self._claims(token['access_token'],profile['client_id'])
            if int(claims['sub'].split(':')[-1])!=profile['character_id']: raise ValueError('Character identity mismatch')
            self._save(profile,token)
            access=token['access_token']
        with httpx.Client(base_url='https://esi.evetech.net',timeout=30,headers={'Authorization':'Bearer '+access,
                           'X-Compatibility-Date':compatibility_date(),'User-Agent':'EveLootAnalyzer/1.0'}) as c:
            skills=c.get(f'/characters/{profile["character_id"]}/skills');skills.raise_for_status()
            standings=c.get(f'/characters/{profile["character_id"]}/standings');standings.raise_for_status()
        if not profile.get('manual_override'):
            profile['skills'] = {str(s['skill_id']):s['active_skill_level'] for s in skills.json()['skills']}
            for name,type_id in SKILL_IDS.items(): profile[name]=profile['skills'].get(str(type_id),0)
            profile['faction']=next((s['standing'] for s in standings.json() if s['from_id']==500001 and s['from_type']=='faction'),0)
            profile['corporation']=next((s['standing'] for s in standings.json() if s['from_id']==1000035 and s['from_type']=='npc_corp'),0)
        return profile
