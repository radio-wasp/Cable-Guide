import os


def _env_bool(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


PORT = int(os.getenv("PORT", "8080"))
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Default Channel Metadata (for self-exported M3U / XMLTV)
CHANNEL_NUMBER = os.getenv("CHANNEL_NUMBER", "03")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "PREVUE GUIDE")
STATION_ID = os.getenv("STATION_ID", "PREVUE CHANNEL")

# Optional External XMLTV URL to populate live channel listings
XMLTV_URL = os.getenv("XMLTV_URL", "").strip()

# Video / HLS Settings
WIDTH = int(os.getenv("WIDTH", "1280"))
HEIGHT = int(os.getenv("HEIGHT", "720"))
FPS = int(os.getenv("FPS", "24"))
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE", "2500k")
HLS_DIR = os.getenv("HLS_DIR", "/tmp/hls")
HLS_TIME = int(os.getenv("HLS_TIME", "2"))
HLS_LIST_SIZE = int(os.getenv("HLS_LIST_SIZE", "8"))

# Rolling Guide & Promo Timing
SCROLL_SPEED = float(os.getenv("SCROLL_SPEED", "38.0"))  # pixels per second at 720p
PROMO_DURATION = float(os.getenv("PROMO_DURATION", "10.0"))  # seconds per top-left/top-right promo card

# Visual CRT Aesthetics
SCANLINES = _env_bool("SCANLINES", True)
CRT_NOISE = _env_bool("CRT_NOISE", True)
CRT_VIGNETTE = _env_bool("CRT_VIGNETTE", True)
TIME_FORMAT_12H = _env_bool("TIME_FORMAT_12H", True)

# Default Audio Settings (overridden by Admin Portal settings.json once saved)
AUDIO_MODE = os.getenv("AUDIO_MODE", "stream").strip().lower()
AUDIO_STREAM_URL = os.getenv(
    "AUDIO_STREAM_URL",
    "https://chi-master3-entry1.leanstream-hd.com:2113/CKULFM",
).strip()

# Refresh Settings
MAX_RSS_FEEDS = 5
REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "15"))
MAX_ITEMS_PER_FEED = int(os.getenv("MAX_ITEMS_PER_FEED", "8"))
