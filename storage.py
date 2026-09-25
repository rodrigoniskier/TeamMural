"""Small DB-API compatibility layer; preserves SQLite development and adds PostgreSQL."""
import sqlite3

class SQLiteConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

class Cursor:
    def __init__(self,cursor,lastrowid=None): self.cursor=cursor; self.lastrowid=lastrowid
    def fetchone(self): return self.cursor.fetchone()
    def fetchall(self): return self.cursor.fetchall()

class PostgresConnection:
    def __init__(self,url):
        import psycopg
        from psycopg.rows import dict_row
        self.conn=psycopg.connect(url,row_factory=dict_row,connect_timeout=10)
    def __enter__(self): return self
    def __exit__(self,typ,value,tb):
        try:
            if typ: self.conn.rollback()
            else: self.conn.commit()
        finally: self.conn.close()
    def execute(self,sql,params=()):
        sql=sql.replace("?","%s")
        if "INSERT OR IGNORE" in sql:
            sql=sql.replace("INSERT OR IGNORE","INSERT")+" ON CONFLICT DO NOTHING"
        needs_id=sql.lstrip().startswith("INSERT INTO") and "channel_members" not in sql
        if needs_id: sql+=" RETURNING id"
        cursor=self.conn.execute(sql,params)
        lastrowid=cursor.fetchone()["id"] if needs_id else None
        return Cursor(cursor,lastrowid)
    def executescript(self,script):
        script=script.replace("INTEGER PRIMARY KEY AUTOINCREMENT","SERIAL PRIMARY KEY").replace(" COLLATE NOCASE","")
        for statement in script.split(";"):
            if statement.strip(): self.conn.execute(statement)

def connect(url,path):
    if url: return PostgresConnection(url)
    conn=sqlite3.connect(path,timeout=10,factory=SQLiteConnection)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
