import os,tempfile,unittest,re
from pathlib import Path
_test_dir=tempfile.TemporaryDirectory()
os.environ.update(PORTFOLIO_DEMO='1',DATABASE_URL='',DATABASE_PATH=str(Path(_test_dir.name)/'test.db'))
from app import app,db_connect
from seed_demo import seed

class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True)
        seed()
    def setUp(self):
        self.client=app.test_client()
        response=self.client.get('/login')
        self.token=re.search(r'name="csrf_token" value="([^"]+)"',response.text)[1]
        self.client.post('/demo/enter',data={'csrf_token':self.token})
        response=self.client.get('/')
        self.token=re.search(r'name="csrf_token" value="([^"]+)"',response.text)[1]
    def test_send_and_read_persisted_message(self):
        response=self.client.post('/api/messages/1',json={'body':'Mensagem sintética do teste.'},headers={'X-CSRF-Token':self.token})
        self.assertEqual(response.status_code,201)
        self.assertTrue(any(row['body']=='Mensagem sintética do teste.' for row in self.client.get('/api/messages/1').json))
    def test_upload_and_admin_disabled(self):
        self.assertEqual(self.client.post('/api/upload/1',headers={'X-CSRF-Token':self.token}).status_code,403)
        self.assertEqual(self.client.get('/admin/users').status_code,403)
    def test_csrf_and_membership(self):
        self.assertEqual(self.client.post('/api/messages/1',json={'body':'test'}).status_code,400)
        with db_connect() as conn:
            cursor=conn.execute("INSERT INTO channels (name,kind) VALUES (?,?)",('Restrito','group'))
            channel=cursor.lastrowid
        self.assertEqual(self.client.get(f'/api/messages/{channel}').status_code,403)
    def test_seed_idempotent_and_unprivileged(self):
        seed()
        with db_connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'],7)
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin'").fetchone()['n'],0)

if __name__=='__main__':unittest.main()
