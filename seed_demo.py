"""Seed only a dedicated PORTFOLIO_DEMO database. Safe to run repeatedly."""
import secrets
from app import PORTFOLIO_DEMO,db_connect,direct_channel
from werkzeug.security import generate_password_hash

def seed():
    if not PORTFOLIO_DEMO: raise RuntimeError('PORTFOLIO_DEMO=1 is required')
    names=['Mariana Costa','Lucas Almeida','Ana Martins','Rafael Oliveira','Clara Mendes','Bruno Carvalho','Helena Duarte']
    with db_connect() as conn:
        ids=[]
        for name in names:
            email=name.split()[0].lower()+'@example.invalid'
            row=conn.execute('SELECT id FROM users WHERE email = ?',(email,)).fetchone()
            if row: ids.append(row['id']);continue
            c=conn.execute('INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)',(name,email,generate_password_hash(secrets.token_urlsafe(32)),'member'));ids.append(c.lastrowid)
        general=conn.execute("SELECT id FROM channels WHERE name='General'").fetchone()['id']
        for uid in ids:conn.execute('INSERT OR IGNORE INTO channel_members (channel_id,user_id) VALUES (?,?)',(general,uid))
        content=[(1,'Bom dia, equipe! O planejamento da semana já está organizado. Podemos concentrar os alinhamentos por aqui.'),(0,'Perfeito, Lucas. Vou consolidar as prioridades e acompanhar as entregas de cada frente.'),(2,'A oficina de integração está confirmada. O material de apoio ficou pronto para a revisão.'),(4,'Revisei o roteiro e deixei os próximos passos mais objetivos. Posso apresentar na nossa reunião.'),(3,'O painel de acompanhamento está atualizado. As demandas de acesso foram encaminhadas.'),(5,'Obrigado! Hoje vou finalizar a conferência dos cadastros fictícios da demonstração.'),(6,'A comunicação para os participantes já está preparada. Aguardo apenas a revisão do texto.'),(0,'Combinado. Vamos registrar o que ficou decidido e manter cada responsável informado.'),(1,'Sugestão de pauta: entregas da semana, impedimentos e próximos passos.'),(2,'Ótima pauta. A reunião pode ser curta e concentrada nas decisões.'),(4,'Enviei a versão revisada na conversa com a Mariana.'),(0,'Recebido. Obrigada, equipe!')]
        for i,(who,body) in enumerate(content):
            if not conn.execute('SELECT id FROM messages WHERE channel_id=? AND body=?',(general,body)).fetchone():
                conn.execute('INSERT INTO messages (channel_id,user_id,body,kind,created_at) VALUES (?,?,?,?,?)',(general,ids[who],body,'text',f'2026-09-25 09:{i*4:02d}:00'))
        for j in [1,2,4]:
            channel=direct_channel(conn,ids[0],ids[j])
            for who,body in [(j,'Olá, Mariana. A revisão do material está concluída. Podemos conferir os próximos passos?'),(0,'Claro! Obrigada por organizar. Vou revisar o roteiro e retorno com os ajustes.'),(j,'Combinado. Deixei os pontos que precisam de decisão destacados no resumo.')]:
                if not conn.execute('SELECT id FROM messages WHERE channel_id=? AND body=?',(channel['id'],body)).fetchone():conn.execute('INSERT INTO messages (channel_id,user_id,body,kind) VALUES (?,?,?,?)',(channel['id'],ids[who],body,'text'))
    print('7 synthetic members, general channel and 3 private conversations ready.')

if __name__=='__main__':seed()
