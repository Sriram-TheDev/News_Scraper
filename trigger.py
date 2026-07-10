import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv()
url = 'https://jit-news-vault.onrender.com/cron-digest'
token = os.environ['CRON_SECRET_TOKEN']

req = urllib.request.Request(
    url,
    headers={'X-Cron-Secret-Token': token},
    method='POST'
)

try:
    with urllib.request.urlopen(req, timeout=120) as r:
        response_data = r.read().decode('utf-8')
        print('SUCCESS:', response_data)
except Exception as e:
    print('Failed:', e)
    if hasattr(e, 'read'):
        try:
            print(e.read().decode('utf-8'))
        except Exception:
            pass
