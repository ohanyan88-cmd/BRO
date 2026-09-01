import sqlite3,tempfile,unittest
from pathlib import Path
from bro_runtime.operations_runtime import RuntimeOperations
from bro_runtime.restore_runtime import RestoreRuntime
class RestoreRuntimeTests(unittest.TestCase):
 def test_verified_backup_can_be_restored_and_drilled(self):
  with tempfile.TemporaryDirectory() as d:
   c=sqlite3.connect(':memory:'); c.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY)'); c.execute("INSERT INTO tasks VALUES ('task:1')"); c.commit()
   backup=Path(d)/'backup.db'; RuntimeOperations(c).backup(backup)
   receipt=RestoreRuntime().drill(backup,Path(d)/'restored.db')
   self.assertTrue(receipt.integrity_ok); self.assertIn('tasks',receipt.restored_tables)
if __name__=='__main__': unittest.main()
