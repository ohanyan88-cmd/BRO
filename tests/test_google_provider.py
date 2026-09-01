import unittest
from bro_runtime.google_provider import GmailSendProvider,CalendarEventProvider,CalendarTarget,GoogleProviderRejected
from bro_runtime.action_runtime import EffectState

class GoogleProviderTests(unittest.TestCase):
 def test_gmail_reconciles_before_send(self):
  calls=[]
  def transport(method,url,token,payload):
   calls.append((method,url,payload));return {'messages':[]} if method=='GET' else {'id':'m1'}
  provider=GmailSendProvider(transport=transport)
  result=provider.invoke({'token':'secret','operation':'gmail.message.ensure','idempotency_key':'k1','to':'a@example.com','subject':'s','body':'b'})
  self.assertEqual([c[0] for c in calls],['GET','POST']);self.assertEqual(result.effect_state,EffectState.POSSIBLE)
 def test_calendar_existing_matching_event_is_confirmed_without_write(self):
  provider=CalendarEventProvider(CalendarTarget('primary'),transport=lambda m,u,t,p:{'id':provider.event_id('k'),'summary':'s','start':{'date':'2026-09-02'},'end':{'date':'2026-09-03'}})
  result=provider.invoke({'token':'secret','operation':'calendar.event.ensure','idempotency_key':'k','summary':'s','start':{'date':'2026-09-02'},'end':{'date':'2026-09-03'}})
  self.assertEqual(result.effect_state,EffectState.CONFIRMED)
 def test_calendar_conflicting_replay_fails_closed(self):
  provider=CalendarEventProvider(CalendarTarget('primary'),transport=lambda m,u,t,p:{'id':provider.event_id('k'),'summary':'other','start':{},'end':{}})
  with self.assertRaises(GoogleProviderRejected):provider.invoke({'token':'secret','operation':'calendar.event.ensure','idempotency_key':'k','summary':'s','start':{},'end':{}})
if __name__=='__main__':unittest.main()
