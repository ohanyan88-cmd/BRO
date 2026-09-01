"""Target-bound Google Gmail and Calendar providers with read-before-write reconciliation."""
from __future__ import annotations
import base64,hashlib,json
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import quote
from urllib.request import Request,urlopen
from .action_runtime import AdapterResult,EffectState
from .provider_adapters import ProviderAdapter
class GoogleProviderRejected(RuntimeError):pass

def _http(method,url,token,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    request=Request(url,data=data,method=method,headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'})
    with urlopen(request,timeout=30) as response:return json.load(response)

@dataclass(frozen=True)
class GmailTarget:
    user_id:str='me'; api_url:str='https://gmail.googleapis.com/gmail/v1'
class GmailSendProvider:
    adapter_id='gmail-send'; version='v1'
    def __init__(self,target:GmailTarget=GmailTarget(),*,transport=None):self.target=target;self.transport=transport or _http
    def adapter(self):return ProviderAdapter(self.adapter_id,'gmail',self.version,('gmail.message.ensure','gmail.message.read'),self.invoke,idempotent_operations=('gmail.message.ensure',),required_secrets=('token',))
    def invoke(self,inputs):
        token=inputs.pop('token',None); operation=inputs.get('operation'); key=str(inputs.get('idempotency_key','')).strip()
        if not token or not key:raise GoogleProviderRejected('mediated token and idempotency key are required')
        message_id=f"<{hashlib.sha256(key.encode()).hexdigest()}@bro.local>"; query=quote(f'rfc822msgid:{message_id}')
        listing=self.transport('GET',f"{self.target.api_url}/users/{quote(self.target.user_id)}/messages?q={query}",token,None)
        matches=listing.get('messages',[]) if isinstance(listing,dict) else []
        if len(matches)>1:raise GoogleProviderRejected('ambiguous Gmail reconciliation identity')
        if operation=='gmail.message.read':return AdapterResult({'exists':bool(matches),'message_id':matches[0]['id'] if matches else None},EffectState.NONE)
        if operation!='gmail.message.ensure':raise GoogleProviderRejected('unsupported Gmail operation')
        if matches:return AdapterResult({'exists':True,'message_id':matches[0]['id']},EffectState.CONFIRMED)
        msg=EmailMessage();msg['To']=str(inputs.get('to',''));msg['Subject']=str(inputs.get('subject',''));msg['Message-ID']=message_id;msg.set_content(str(inputs.get('body','')))
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip('=')
        created=self.transport('POST',f"{self.target.api_url}/users/{quote(self.target.user_id)}/messages/send",token,{'raw':raw})
        return AdapterResult({'exists':True,'message_id':created.get('id')},EffectState.POSSIBLE)

@dataclass(frozen=True)
class CalendarTarget:
    calendar_id:str; api_url:str='https://www.googleapis.com/calendar/v3'
class CalendarEventProvider:
    adapter_id='google-calendar-event';version='v1'
    def __init__(self,target:CalendarTarget,*,transport=None):
        if not target.calendar_id:raise GoogleProviderRejected('calendar_id is required')
        self.target=target;self.transport=transport or _http
    def adapter(self):return ProviderAdapter(self.adapter_id,'google-calendar',self.version,('calendar.event.ensure','calendar.event.read'),self.invoke,idempotent_operations=('calendar.event.ensure',),required_secrets=('token',))
    @staticmethod
    def event_id(key):return hashlib.sha256(key.encode()).hexdigest()[:40]
    def invoke(self,inputs):
        token=inputs.pop('token',None);key=str(inputs.get('idempotency_key','')).strip();op=inputs.get('operation')
        if not token or not key:raise GoogleProviderRejected('mediated token and idempotency key are required')
        eid=self.event_id(key);base=f"{self.target.api_url}/calendars/{quote(self.target.calendar_id,safe='')}/events"; existing=self.transport('GET',f'{base}/{eid}',token,None)
        exists=bool(existing and existing.get('id')==eid)
        if op=='calendar.event.read':return AdapterResult({'exists':exists,'event_id':eid},EffectState.NONE)
        if op!='calendar.event.ensure':raise GoogleProviderRejected('unsupported Calendar operation')
        desired={'id':eid,'summary':inputs.get('summary'),'start':inputs.get('start'),'end':inputs.get('end')}
        if exists:
            if any(existing.get(k)!=v for k,v in desired.items()):raise GoogleProviderRejected('conflicting Calendar replay')
            return AdapterResult({'exists':True,'event_id':eid},EffectState.CONFIRMED)
        created=self.transport('POST',base,token,desired)
        return AdapterResult({'exists':True,'event_id':created.get('id')},EffectState.POSSIBLE)
