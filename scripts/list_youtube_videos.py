import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

token_path = Path('~/.openmontage/youtube_token.json').expanduser()
token_data = json.loads(token_path.read_text())
creds = Credentials.from_authorized_user_info(token_data)
youtube = build('youtube', 'v3', credentials=creds)

channels_response = youtube.channels().list(
    mine=True,
    part='contentDetails'
).execute()

uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

playlist_response = youtube.playlistItems().list(
    playlistId=uploads_playlist_id,
    part='snippet,contentDetails',
    maxResults=20
).execute()

print('--- RECENT YOUTUBE UPLOADS ---')
for item in playlist_response.get('items', []):
    video_id = item['contentDetails']['videoId']
    title = item['snippet']['title']
    published_at = item['snippet']['publishedAt']
    print(f"ID: {video_id} | Title: {title} | Published: {published_at}")
