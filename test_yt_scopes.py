import sys, os
from pathlib import Path

# Add project root to sys path
sys.path.insert(0, os.environ.get("OPENMONTAGE_ROOT", str(Path(__file__).resolve().parent)))

from tools.publishers.youtube_publisher import YoutubePublisher

# Just print the scopes and see what it does
pub = YoutubePublisher()
print("YoutubePublisher scopes:", pub.SCOPES)
# Try checking one of the target videos
status = pub.check_video_published("vq610Irj9O8")
print("\ncheck_video_published result:")
print(status)
