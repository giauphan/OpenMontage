import os
from dotenv import load_dotenv
import requests

load_dotenv('/home/genro68/OpenMontage/.env', override=True)
token = os.environ.get('TOKEN_FACEBOOK')
res = requests.get(f'https://graph.facebook.com/v26.0/me/permissions?access_token={token}').json()
for item in res.get('data', []):
    print(f"{item['permission']}: {item['status']}")
