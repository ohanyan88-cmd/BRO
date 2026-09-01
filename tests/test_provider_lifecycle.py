import sqlite3,unittest
from bro_runtime.provider_lifecycle import ProviderLifecycleStore,ProviderConnectionState,ProviderLifecycleRejected
from bro_runtime.provider_adapters import ProviderAdapter
from bro_runtime.action_runtime import AdapterResult,EffectState
class ProviderLifecycleTests(unittest.TestCase):
 def test_guard_opens_circuit_after_threshold_and_recovers_on_success(self):
  connection=sqlite3.connect(':memory:');life=ProviderLifecycleStore(connection,failure_threshold=2);calls={'n':0}
  def invoke(inputs):
   calls['n']+=1
   if calls['n']<3:raise TimeoutError('down')
   return AdapterResult({},EffectState.NONE)
  guarded=life.guard(ProviderAdapter('a','p','v1',('read',),invoke))
  with self.assertRaises(TimeoutError):guarded.invoke({})
  self.assertEqual(life.fetch('p','a','v1').state,ProviderConnectionState.DEGRADED)
  with self.assertRaises(TimeoutError):guarded.invoke({})
  self.assertEqual(life.fetch('p','a','v1').state,ProviderConnectionState.UNAVAILABLE)
  with self.assertRaises(ProviderLifecycleRejected):guarded.invoke({})
  self.assertEqual(calls['n'],2)
if __name__=='__main__':unittest.main()
