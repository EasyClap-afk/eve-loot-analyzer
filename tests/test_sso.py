import time
from types import SimpleNamespace
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from app import sso

def test_jwt_validation_rejects_wrong_audience_client_and_expiry(monkeypatch):
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    real_client=httpx.Client
    def handler(request):
        return httpx.Response(200,json={'issuer':'https://login.eveonline.com','jwks_uri':'https://login.eveonline.com/oauth/jwks'})
    monkeypatch.setattr(sso.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(sso.jwt,'PyJWKClient',lambda _:SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=private.public_key())))
    claims={'iss':'https://login.eveonline.com','sub':'CHARACTER:EVE:123','aud':'EVE Online','azp':'client','exp':time.time()+600}
    provider=sso.SSO()
    assert provider._claims(jwt.encode(claims,private,algorithm='RS256'),'client')['sub']=='CHARACTER:EVE:123'
    for patch in [{'aud':'attacker'},{'iss':'https://attacker'},{'azp':'attacker'},{'exp':time.time()-120}]:
        with pytest.raises((jwt.InvalidTokenError,ValueError)):
            provider._claims(jwt.encode(claims|patch,private,algorithm='RS256'),'client')
    # Real SSO tokens may be issued a few seconds ahead of the local clock.
    for field in ('iat','nbf'):
        assert provider._claims(jwt.encode(claims|{field:time.time()+5},private,algorithm='RS256'),'client')['sub']=='CHARACTER:EVE:123'
        with pytest.raises(ValueError,match='Synchronizuj teraz'):
            provider._claims(jwt.encode(claims|{field:time.time()+120},private,algorithm='RS256'),'client')
    other_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    with pytest.raises(jwt.InvalidSignatureError):
        provider._claims(jwt.encode(claims|{'iat':time.time()+5},other_key,algorithm='RS256'),'client')

def test_sync_raw_standings_active_skills_and_manual_override(monkeypatch):
    real_client=httpx.Client
    def handler(request):
        if request.url.path.endswith('/skills'):
            return httpx.Response(200,json={'skills':[{'skill_id':16622,'active_skill_level':5},{'skill_id':3380,'active_skill_level':4}]})
        return httpx.Response(200,json=[{'from_id':500001,'from_type':'faction','standing':6.5},{'from_id':1000035,'from_type':'npc_corp','standing':8.1},{'from_id':99,'from_type':'npc_corp','standing':10}])
    monkeypatch.setattr(sso.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    provider=sso.SSO();provider.access['P']=('memory-only',time.time()+600)
    p=provider.sync({'name':'P','character_id':123})
    assert p['accounting']==5 and p['industry']==4 and p['faction']==6.5 and p['corporation']==8.1
    p.update(manual_override=True,accounting=2,faction=-1)
    assert provider.sync(p)['accounting']==2 and p['faction']==-1

def test_token_storage_and_disconnect(monkeypatch):
    vault={}
    monkeypatch.setattr(sso.keyring,'set_password',lambda service,name,value:vault.update({(service,name):value}))
    monkeypatch.setattr(sso.keyring,'delete_password',lambda service,name:vault.pop((service,name)))
    provider=sso.SSO();p={'name':'P','character_id':123,'character_name':'Pilot'}
    provider._save(p,{'access_token':'only-memory','refresh_token':'secret-vault','expires_in':1200})
    assert vault[(sso.SERVICE,'P')]=='secret-vault' and 'refresh_token' not in p
    provider.disconnect(p)
    assert not vault and not provider.access and 'character_id' not in p
