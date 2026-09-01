import sqlite3,unittest
from bro_runtime.incident_runtime import IncidentRuntime,IncidentRejected,IncidentState
class IncidentRuntimeTests(unittest.TestCase):
 def test_incident_requires_owner_and_recovery_evidence_to_resolve(self):
  r=IncidentRuntime(sqlite3.connect(':memory:')); i=r.open(source_ref='provider:gmail',severity='P1',summary='provider unavailable'); i=r.acknowledge(i.incident_id,owner='operator:1')
  with self.assertRaises(IncidentRejected): r.resolve(i.incident_id,owner='operator:2',recovery_evidence_ref='evidence:1')
  done=r.resolve(i.incident_id,owner='operator:1',recovery_evidence_ref='evidence:1'); self.assertEqual(done.state,IncidentState.RESOLVED)
if __name__=='__main__': unittest.main()
