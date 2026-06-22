import sqlite3
conn = sqlite3.connect('bharatbot.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute('SELECT * FROM sessions LIMIT 5')
rows = cursor.fetchall()
print(f'Total sessions in DB: {len(rows)}')
for row in rows:
    sid = row['session_id']
    uid = row['user_id']
    title = row['title']
    created = row['created_at']
    is_active = row['is_active']
    print(f'  session_id: {sid}')
    print(f'  user_id: {uid}')
    print(f'  title: {title}')
    print(f'  created_at: {created}')
    print(f'  is_active: {is_active}')
    print()

conn.close()
