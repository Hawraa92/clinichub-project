# backup_db.py  (ضعيه بجذر المشروع)
import os, datetime, subprocess, shutil
from decouple import config

BACKUP_DIR = 'db_backups'
os.makedirs(BACKUP_DIR, exist_ok=True)

ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
fname = f"{BACKUP_DIR}/clinic_{ts}.dump"  # صيغة pg_dump المخصّصة -F c

cmd = [
    'pg_dump', '-h', config('DB_HOST', 'localhost'),
    '-p', config('DB_PORT', '5432'),
    '-U', config('DB_USER'),
    '-F', 'c', '-b', '-v', '-f', fname,
    config('DB_NAME'),
]

env = os.environ.copy()
env['PGPASSWORD'] = config('DB_PASSWORD')  # يتفادى خطأ المصادقة

try:
    subprocess.check_call(cmd, env=env)
    print(f"✅ Backup created: {fname}")
except subprocess.CalledProcessError:
    print("❌ Backup failed – check credentials or pg_dump path")

# تنظيف النسخ الأقدم من 30 يوم
for f in os.listdir(BACKUP_DIR):
    path = os.path.join(BACKUP_DIR, f)
    if os.path.getmtime(path) < (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp():
        os.remove(path)
