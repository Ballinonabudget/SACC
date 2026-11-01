"""Loopback-only API for the isolated recovered-media catalogue."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from .library import LibraryDB, StaleReview, DEFAULT_ROOT, DEFAULT_RECOVERY


class LocalLibraryGuard:
    """Shared guard also closes legacy arbitrary-path routes around private media."""
    def __init__(self, app):self.app=app

    async def __call__(self, scope, receive, send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]));host=headers.get(b'host',b'').decode()
        parsed=urlsplit('http://'+host)
        client=(scope.get('client') or ('',0))[0]
        try:local=ipaddress.ip_address(client).is_loopback
        except ValueError:local=client=='testclient'
        allowed=parsed.hostname in {'localhost','127.0.0.1','::1'}
        origin=headers.get(b'origin',b'').decode()
        if not local or not allowed or headers.get(b'sec-fetch-site')==b'cross-site':
            return await JSONResponse({'detail':'Local access required'},403)(scope,receive,send)
        if origin:
            o=urlsplit(origin)
            if o.scheme not in {'http','https'} or o.hostname not in {'localhost','127.0.0.1','::1'}:
                return await JSONResponse({'detail':'Local origin required'},403)(scope,receive,send)
            if scope['path'].startswith('/api/library') and origin!='http://'+host:
                return await JSONResponse({'detail':'Same-origin library access required'},403)(scope,receive,send)
        if scope['path'].startswith('/api/') and not scope['path'].startswith('/api/library'):
            from urllib.parse import parse_qs
            values=list(parse_qs(scope.get('query_string',b'').decode()).values())
            payload=[]
            if b'application/json' in headers.get(b'content-type',b''):
                body=b''
                while True:
                    event=await receive();body+=event.get('body',b'')
                    if len(body)>2*1024*1024:
                        return await JSONResponse({'detail':'JSON request too large'},413)(scope,receive,send)
                    if not event.get('more_body'):break
                try:payload=json.loads(body) if body else []
                except ValueError:payload=[]
                delivered=False
                async def replay():
                    nonlocal delivered
                    if not delivered:delivered=True;return {'type':'http.request','body':body,'more_body':False}
                    return await receive()
                next_receive=replay
            else:next_receive=receive
            def strings(v):
                if isinstance(v,str):yield v
                elif isinstance(v,dict):
                    for x in v.values():yield from strings(x)
                elif isinstance(v,list):
                    for x in v:yield from strings(x)
            roots=[DEFAULT_RECOVERY.parent,DEFAULT_ROOT.parent,LibraryDB().path.parent]
            roots.extend(Path(p) for p in os.getenv('SACC_LIBRARY_PROTECTED_ROOTS','').split(os.pathsep) if p)
            for value in strings([values,payload]):
                if not value.startswith(('/','~')):continue
                path=Path(value).expanduser().resolve()
                if any(path==r.resolve() or path.is_relative_to(r.resolve()) or r.resolve().is_relative_to(path) for r in roots):
                    return await JSONResponse({'detail':'Use the protected Library API for recovery data'},403)(scope,receive,send)
            return await self.app(scope,next_receive,send)
        return await self.app(scope,receive,send)


router=APIRouter(prefix='/api/library')
_sessions={}
COOKIE='sacc_library_session'


def _authorize(request,write=False):
    sid=request.cookies.get(COOKIE);entry=_sessions.get(sid)
    if not entry or entry[1]<time.monotonic():raise HTTPException(401,'Open a Library session first')
    if write and not secrets.compare_digest(request.headers.get('X-SACC-Library-Token',''),entry[0]):
        raise HTTPException(403,'Invalid Library request token')


def _call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except StaleReview as e:raise HTTPException(409,str(e))
    except KeyError:raise HTTPException(404,'Unknown Library record')
    except (ValueError,TypeError,FileNotFoundError) as e:raise HTTPException(400,str(e))


@router.get('/session')
def session():
    now=time.monotonic()
    for key in list(_sessions):
        if _sessions[key][1]<now:del _sessions[key]
    if len(_sessions)>1000:raise HTTPException(429,'Too many local sessions')
    sid=secrets.token_urlsafe(32);token=secrets.token_urlsafe(32);_sessions[sid]=(token,now+12*3600)
    response=JSONResponse({'csrf_token':token,'ready':LibraryDB().path.is_file(),'mode':'isolated_copy'})
    response.set_cookie(COOKIE,sid,httponly=True,samesite='strict',max_age=12*3600,path='/api/library')
    response.headers['Cache-Control']='no-store'
    return response


@router.get('/status')
def status(request:Request):
    _authorize(request)
    if not LibraryDB().path.is_file():return {'ready':False,'mode':'isolated_copy','totals':{},'imports':[]}
    return _call(LibraryDB().status)


@router.get('/facets')
def facets(request:Request):_authorize(request);return _call(LibraryDB().facets)


@router.get('/items')
def items(request:Request,limit:int=30,offset:int=0):
    _authorize(request);return _call(LibraryDB().items,dict(request.query_params),limit,offset)


@router.get('/items/{oid}')
def detail(oid:str,request:Request):_authorize(request);return _call(LibraryDB().detail,oid)


@router.get('/assets/{oid}')
def asset(oid:str,request:Request,download:bool=False):
    _authorize(request);a=_call(LibraryDB().asset,oid)
    safe=a['mime_type'] in {'image/jpeg','image/png','image/gif','image/webp','video/mp4','video/quicktime'}
    return FileResponse(a['path'],media_type=a['mime_type'] if safe else 'application/octet-stream',filename=a['name'],
        content_disposition_type='attachment' if download or not safe else 'inline',
        headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.post('/reviews')
async def reviews(request:Request):
    _authorize(request,True);p=await request.json()
    return _call(LibraryDB().review,p.get('items'),p.get('action'),p.get('value'),p.get('reviewer',''),p.get('evidence',''),p.get('historical_evidence',''))


@router.get('/directory')
def directory(request:Request):_authorize(request);return _call(LibraryDB().directory)


@router.post('/directory')
async def add_directory(request:Request):
    _authorize(request,True);p=await request.json()
    return _call(LibraryDB().import_directory,p.get('directory'),p.get('reviewer',''),p.get('evidence',''))


def preview(filters=None,ids=None):
    from .organization import create_plan
    db=LibraryDB();root=db.path.parent.parent
    return create_plan(db.layout_rows(filters,ids),root/'organized',root/'organization-plans',
                       binding={'library_db':str(db.path)},strategy='clone')


@router.post('/organization/preview')
async def organization_preview(request:Request):
    _authorize(request,True);p=await request.json()
    if 'ids' in p and 'filters' in p:raise HTTPException(400,'Choose IDs or filters')
    return _call(preview,p.get('filters'),p.get('ids'))


@router.get('/organization/plans/{plan_id}')
def organization_plan(plan_id:str,request:Request):
    _authorize(request)
    if len(plan_id)!=64 or any(c not in '0123456789abcdef' for c in plan_id):raise HTTPException(400,'Invalid plan ID')
    from .organization import inspect_plan
    return _call(inspect_plan,LibraryDB().path.parent.parent/'organization-plans'/plan_id)
