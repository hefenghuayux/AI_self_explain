import pymysql

conn = pymysql.connect(
    host="8.131.237.45", port=3306, user="devuser", password="iHTrVUPvBwmrTg5O", connect_timeout=8
)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM ai_self_explain.users")
print("ai_self_explain.users count:", cur.fetchone()[0])
cur.execute("SELECT username, role FROM ai_self_explain.users ORDER BY id LIMIT 10")
for r in cur.fetchall():
    print("  user:", r)

cur.execute("SELECT COUNT(*) FROM tbox_test.sys_user WHERE identity=1")
print("sys_user identity=1:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM tbox_test.sys_user WHERE identity=0 AND status=1")
print("sys_user identity=0 active:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM tbox_test.sys_user_student")
print("sys_user_student assoc:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM tbox_test.student WHERE account IS NOT NULL AND password IS NOT NULL")
print("students with account+password:", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM tbox_test.student WHERE status=1")
print("students status=1:", cur.fetchone()[0])
cur.execute("SELECT COUNT(DISTINCT user_id) FROM tbox_test.sys_user_student")
print("distinct users with students:", cur.fetchone()[0])
cur.close()
conn.close()
