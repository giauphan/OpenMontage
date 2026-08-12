import os
from dotenv import load_dotenv
import urllib.request, json

load_dotenv('/home/genro68/OpenMontage/.env', override=True)
token = os.environ.get('TOKEN_FACEBOOK')
url = f'https://graph.facebook.com/v26.0/me/accounts?fields=name,id,instagram_business_account&access_token={token}'
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
        print('Pages found:', len(data.get('data', [])))
        for page in data.get('data', []):
            print(f"  ID: {page['id']}, Name: {page.get('name')}, IG: {page.get('instagram_business_account')}")
except urllib.error.HTTPError as e:
    print('HTTP ERROR:', e.code)
    print(e.read().decode())
