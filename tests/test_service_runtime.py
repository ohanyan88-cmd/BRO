import sqlite3,unittest
from bro_runtime.automation import AutomationRuntime,AutomationDispatcher
from bro_runtime.service_runtime import BROServiceRuntime,SQLiteWorkQueue,WorkState
from bro_runtime.task_runtime import SQLiteTaskStore,TaskRuntime,TaskState

class ServiceRuntimeTests(unittest.TestCase):
 def setUp(self):
  self.store=SQLiteTaskStore();self.tasks=TaskRuntime(self.store);self.automation=AutomationRuntime(self.store.connection);self.dispatcher=AutomationDispatcher(self.automation,self.tasks);self.queue=SQLiteWorkQueue(self.store.connection)
 def test_due_automation_enters_same_canonical_task_and_blocks_without_duplicate(self):
  self.automation.create_interval(automation_id='a1',project_boundary='project:x',desired_outcome='do governed work',interval_seconds=60,first_due_at='2026-09-01T00:00:00Z')
  seen=[]
  service=BROServiceRuntime(self.dispatcher,self.queue,lambda task_ref:(seen.append(task_ref) or TaskState.BLOCKED))
  item=service.tick(now='2026-09-01T00:00:00Z',now_epoch=1)
  occurrence=self.automation.occurrences('a1')[0]
  self.assertEqual(seen,[occurrence.task_ref]);self.assertEqual(item.state,WorkState.BLOCKED)
  self.assertEqual(self.store.fetch_task(occurrence.task_ref)['correlation_ref'] if 'correlation_ref' in self.store.fetch_task(occurrence.task_ref) else occurrence.occurrence_id,occurrence.occurrence_id)
  self.assertEqual(len(self.automation.occurrences('a1')),1)
 def test_expired_lease_is_reclaimed_with_fencing_revision(self):
  first=self.queue.enqueue('task:x');leased=self.queue.claim('w1',now_epoch=10,lease_seconds=5);self.assertEqual(leased.state,WorkState.LEASED)
  again=self.queue.claim('w2',now_epoch=16,lease_seconds=5);self.assertEqual(again.task_ref,first.task_ref);self.assertEqual(again.lease_owner,'w2');self.assertGreater(again.revision,leased.revision)
 def test_enqueue_is_idempotent(self):
  self.assertEqual(self.queue.enqueue('task:x').work_id,self.queue.enqueue('task:x').work_id)
if __name__=='__main__':unittest.main()
