import sqlite3,unittest
from bro_runtime.notification_runtime import NotificationRuntime,DeliveryState
class NotificationRuntimeTests(unittest.TestCase):
 def test_delivery_is_idempotent_and_bound_to_task(self):
  r=NotificationRuntime(sqlite3.connect(':memory:')); n=r.create(task_ref='task:1',channel='email',recipient='owner@example.test',body='Approval required',idempotency_key='approval:1')
  calls=[]
  def send(x): calls.append(x.task_ref); return {'provider_ref':'message:1'}
  self.assertEqual(r.deliver('approval:1',send)['provider_ref'],'message:1'); self.assertEqual(r.deliver('approval:1',send)['provider_ref'],'message:1')
  self.assertEqual(calls,['task:1']); self.assertEqual(r.fetch('approval:1').state,DeliveryState.SENT)
if __name__=='__main__': unittest.main()
