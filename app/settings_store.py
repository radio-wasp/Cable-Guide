import json
import logging
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

from app import config

logger = logging.getLogger("cable-guide.settings")


def _default_custom_channels() -> List[Dict[str, Any]]:
    """
    Authentic 1996-1998 Prevue Channel lineup starting with the exact rows
    shown in the reference capture (55 HOT CH, 56 HBO2, 57 SHOW, 14 MAX, etc.).
    """
    return [
        {
            "id": "ch-55",
            "number": "55",
            "callsign": "HOT CH",
            "color_Style": "sky_blue",
            "enabled": True,
            "programs": [
                {
                    "title": '"Jackie Chan\'s First Strike"',
                    "rating": "PG-13",
                    "year": "1996",
                    "desc": "",
                    "offset_min": -30,
                    "duration_min": 90,
                },
                {
                    "title": '"Star Trek: First Contact"',
                    "rating": "PG-13",
                    "year": "1996",
                    "desc": "Patrick Stewart.",
                    "offset_min": 60,
                    "duration_min": 120,
                },
            ],
        },
        {
            "id": "ch-56",
            "number": "56",
            "callsign": "HBO2",
            "color_Style": "crimson",
            "enabled": True,
            "programs": [
                {
                    "title": '"Legends of the North"',
                    "rating": "PG",
                    "year": "1995",
                    "desc": "Randy Quaid.",
                    "offset_min": -15,
                    "duration_min": 75,
                },
                {
                    "title": '(11:45) "A River Runs Through It"',
                    "rating": "PG",
                    "year": "1992",
                    "desc": "Brad Pitt.",
                    "offset_min": 60,
                    "duration_min": 120,
                },
            ],
        },
        {
            "id": "ch-57",
            "number": "57",
            "callsign": "SHOW",
            "color_Style": "crimson",
            "enabled": True,
            "programs": [
                {
                    "title": '"Big Bully"',
                    "rating": "PG",
                    "year": "1996",
                    "desc": "Rick Moranis.",
                    "offset_min": -30,
                    "duration_min": 90,
                },
                {
                    "title": "Family Business",
                    "rating": "R",
                    "year": "1989",
                    "desc": "Sean Connery.",
                    "offset_min": 60,
                    "duration_min": 90,
                },
            ],
        },
        {
            "id": "ch-14",
            "number": "14",
            "callsign": "MAX",
            "color_Style": "crimson",
            "enabled": True,
            "programs": [
                {
                    "title": '"Black Sheep"',
                    "rating": "PG-13",
                    "year": "1996",
                    "desc": "Chris Farley, David Spade.",
                    "offset_min": 0,
                    "duration_min": 90,
                },
                {
                    "title": '"Twister"',
                    "rating": "PG-13",
                    "year": "1996",
                    "desc": "Helen Hunt, Bill Paxton.",
                    "offset_min": 90,
                    "duration_min": 120,
                },
            ],
        },
        {
            "id": "ch-04",
            "number": "4",
            "callsign": "NBC",
            "color_Style": "navy",
            "enabled": True,
            "programs": [
                {
                    "title": "Leeza",
                    "rating": "TV-G",
                    "year": "",
                    "desc": "Talk & interviews.",
                    "offset_min": 0,
                    "duration_min": 60,
                },
                {
                    "title": "Sunset Beach",
                    "rating": "TV-PG",
                    "year": "",
                    "desc": "Daytime drama.",
                    "offset_min": 60,
                    "duration_min": 60,
                },
            ],
        },
        {
            "id": "ch-07",
            "number": "7",
            "callsign": "ABC",
            "color_Style": "navy",
            "enabled": True,
            "programs": [
                {
                    "title": "The View",
                    "rating": "TV-G",
                    "year": "",
                    "desc": "Celebrity guests.",
                    "offset_min": 0,
                    "duration_min": 60,
                },
                {
                    "title": "Port Charles",
                    "rating": "TV-PG",
                    "year": "",
                    "desc": "",
                    "offset_min": 60,
                    "duration_min": 30,
                },
                {
                    "title": "All My Children",
                    "rating": "TV-PG",
                    "year": "",
                    "desc": "",
                    "offset_min": 90,
                    "duration_min": 60,
                },
            ],
        },
        {
            "id": "ch-10",
            "number": "10",
            "callsign": "ASN",
            "color_Style": "sky_blue",
            "enabled": True,
            "programs": [
                {
                    "title": "Atlantic Pulse & Community Bulletin",
                    "rating": "",
                    "year": "",
                    "desc": "Local News & Weather.",
                    "offset_min": -30,
                    "duration_min": 90,
                },
                {
                    "title": "Maritime Noon",
                    "rating": "",
                    "year": "",
                    "desc": "Live Call-In.",
                    "offset_min": 60,
                    "duration_min": 60,
                },
            ],
        },
        {
            "id": "ch-24",
            "number": "24",
            "callsign": "ESPN",
            "color_Style": "navy",
            "enabled": True,
            "programs": [
                {
                    "title": "SportsCenter",
                    "rating": "",
                    "year": "",
                    "desc": "Highlights & scores.",
                    "offset_min": 0,
                    "duration_min": 60,
                },
                {
                    "title": "NFL Films Presents",
                    "rating": "",
                    "year": "",
                    "desc": "Gridiron classics.",
                    "offset_min": 60,
                    "duration_min": 30,
                },
                {
                    "title": "NHL 2Night",
                    "rating": "",
                    "year": "",
                    "desc": "",
                    "offset_min": 90,
                    "duration_min": 30,
                },
            ],
        },
        {
            "id": "ch-32",
            "number": "32",
            "callsign": "CNN",
            "color_Style": "navy",
            "enabled": True,
            "programs": [
                {
                    "title": "CNN Today",
                    "rating": "",
                    "year": "",
                    "desc": "World & national news.",
                    "offset_min": -30,
                    "duration_min": 90,
                },
                {
                    "title": "Burden of Proof",
                    "rating": "",
                    "year": "",
                    "desc": "Legal analysis.",
                    "offset_min": 60,
                    "duration_min": 30,
                },
            ],
        },
        {
            "id": "ch-38",
            "number": "38",
            "callsign": "USA",
            "color_Style": "sky_blue",
            "enabled": True,
            "programs": [
                {
                    "title": "Wings",
                    "rating": "TV-PG",
                    "year": "",
                    "desc": "",
                    "offset_min": 0,
                    "duration_min": 30,
                },
                {
                    "title": "Walker, Texas Ranger",
                    "rating": "TV-PG",
                    "year": "",
                    "desc": "Chuck Norris.",
                    "offset_min": 30,
                    "duration_min": 60,
                },
            ],
        },
        {
            "id": "ch-45",
            "number": "45",
            "callsign": "TNT",
            "color_Style": "navy",
            "enabled": True,
            "programs": [
                {
                    "title": "Babylon 5",
                    "rating": "TV-PG",
                    "year": "",
                    "desc": "Sci-Fi Series.",
                    "offset_min": 0,
                    "duration_min": 60,
                },
                {
                    "title": "ER",
                    "rating": "TV-14",
                    "year": "",
                    "desc": "County General.",
                    "offset_min": 60,
                    "duration_min": 60,
                },
            ],
        },
    ]


def _default_settings() -> Dict[str, Any]:
    default_preset_id = "preset-ckulfm"
    presets = []
    if config.AUDIO_STREAM_URL:
        presets.append({
            "id": default_preset_id,
            "name": "CKUL-FM (Default Stream)",
            "url": config.AUDIO_STREAM_URL,
        })

    return {
        # Top-Left Quadrant Customizable Promo / Bulletin Messages (Prevue 4-line style)
        "custom_messages": [
            {
                "id": "msg-1",
                "network": "Cinemax",
                "title": '"Black Sheep"',
                "rating": "PG-13",
                "day_time": "Wednesday",
                "channel_info": "Channel 14",
                "enabled": True,
            },
            {
                "id": "msg-2",
                "network": "Hot Choice PPV",
                "title": '"Jackie Chan\'s First Strike"',
                "rating": "PG-13",
                "day_time": "Now Playing",
                "channel_info": "Channel 55",
                "enabled": True,
            },
            {
                "id": "msg-3",
                "network": "HBO2 Feature",
                "title": '"Legends of the North"',
                "rating": "PG",
                "day_time": "Today at 10:30 AM",
                "channel_info": "Channel 56",
                "enabled": True,
            },
            {
                "id": "msg-4",
                "network": "Cable System Notice",
                "title": "Community Bulletin Board",
                "rating": "",
                "day_time": "Local News & Weather",
                "channel_info": "Tune to Channel 10",
                "enabled": True,
            },
        ],
        # Top-Right Quadrant Feature / Video Window Slides (with lower-third REEL TALK style overlay)
        "right_deck_slides": [
            {
                "id": "slide-1",
                "title": "REEL TALK",
                "subtitle": "DAVID SPADE",
                "theme": "reel_talk",
                "image_url": "",
                "enabled": True,
            },
            {
                "id": "slide-2",
                "title": "PREVUE TONIGHT",
                "subtitle": "BOX OFFICE HITS",
                "theme": "cinema",
                "image_url": "",
                "enabled": True,
            },
            {
                "id": "slide-3",
                "title": "HOLLYWOOD INSIDER",
                "subtitle": "BEHIND THE SCENES",
                "theme": "studio",
                "image_url": "",
                "enabled": True,
            },
        ],
        # In-Grid Rolling Custom Messages (interleaved into the scrolling channel grid)
        "grid_messages": [
            {
                "id": "gmsg-1",
                "label": "NOTICE",
                "text": 'WELCOME TO THE PREVUE GUIDE — YOUR 24-HOUR ON-SCREEN CABLE PROGRAMMING GUIDE',
                "color_style": "sky_blue",
                "enabled": True,
            },
            {
                "id": "gmsg-2",
                "label": "PPV INFO",
                "text": 'ORDER HIT MOVIES ON CH 55 HOT CHOICE! USE YOUR REMOTE OR CALL CUSTOMER SERVICE',
                "color_style": "crimson",
                "enabled": True,
            },
        ],
        # EPG / Channel Lineup Configuration
        "epg": {
            "xmltv_url": config.XMLTV_URL,
            "use_custom_channels": True,
        },
        "custom_channels": _default_custom_channels(),
        # Optional RSS Feeds (up to 5, can be shown in Top-Left message rotation)
        "rss_feeds": [
            {
                "id": "feed-1",
                "name": "CBC Top Stories",
                "url": "https://www.cbc.ca/webfeed/rss/rss-topstories",
                "enabled": True,
            },
        ],
        # Radio Station Presets & Audio Mode
        "radio_presets": presets,
        "active_radio_id": default_preset_id if presets else None,
        "audio_mode": config.AUDIO_MODE if config.AUDIO_MODE in ("stream", "hum", "silent") else "hum",
        # Display & CRT Settings
        "display": {
            "channel_number": config.CHANNEL_NUMBER,
            "channel_name": config.CHANNEL_NAME,
            "scroll_speed": config.SCROLL_SPEED,
            "promo_duration": config.PROMO_DURATION,
            "include_rss_in_topleft": False,
            "show_grid_messages": True,
            "time_format_12h": config.TIME_FORMAT_12H,
            "scanlines": config.SCANLINES,
            "crt_noise": config.CRT_NOISE,
            "crt_vignette": config.CRT_VIGNETTE,
        },
    }


class SettingsStore:
    """
    Thread-safe persistent configuration store (/app/data/settings.json) for:
    - Top-Left custom Prevue promo/bulletin messages
    - Top-Right feature window slides (with lower-third overlay)
    - In-grid rolling custom announcement banners
    - Custom TV channels & external XMLTV URL
    - Optional RSS feeds (up to 5)
    - Radio station presets + active station / audio mode
    - Scroll speed & CRT visual settings
    """

    def __init__(self, path: str = config.SETTINGS_FILE) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = _default_settings()
        self._load()

    def _load(self) -> None:
        with self._lock:
            try:
                if os.path.exists(self._path):
                    with open(self._path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        defaults = _default_settings()
                        for k, v in loaded.items():
                            if k in ("display", "epg") and isinstance(v, dict):
                                merged = dict(defaults.get(k, {}))
                                merged.update(v)
                                defaults[k] = merged
                            else:
                                defaults[k] = v
                        defaults["rss_feeds"] = list(defaults.get("rss_feeds", []))[: config.MAX_RSS_FEEDS]
                        self._data = defaults
                        logger.info("Loaded settings from %s", self._path)
                        return
            except Exception as exc:
                logger.warning("Could not load settings from %s: %s", self._path, exc)
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception as exc:
            logger.warning("Could not persist settings to %s: %s", self._path, exc)

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    # --- Top-Left Custom Promo / Bulletin Messages ---

    def get_custom_messages(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("custom_messages", []))

    def add_custom_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        title = str(payload.get("title", "")).strip()
        network = str(payload.get("network", "")).strip()
        if not title and not network:
            raise ValueError("At least a Title/Message or Header/Network is required.")
        with self._lock:
            msgs = list(self._data.get("custom_messages", []))
            msg = {
                "id": f"msg-{uuid.uuid4().hex[:8]}",
                "network": network[:40],
                "title": title[:60],
                "rating": str(payload.get("rating", "")).strip().upper()[:10],
                "day_time": str(payload.get("day_time", "")).strip()[:40],
                "channel_info": str(payload.get("channel_info", "")).strip()[:40],
                "enabled": bool(payload.get("enabled", True)),
            }
            msgs.append(msg)
            self._data["custom_messages"] = msgs
            self._save_unlocked()
            return msg

    def update_custom_message(self, msg_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            for m in self._data.get("custom_messages", []):
                if m.get("id") == msg_id:
                    if "network" in payload:
                        m["network"] = str(payload["network"]).strip()[:40]
                    if "title" in payload:
                        m["title"] = str(payload["title"]).strip()[:60]
                    if "rating" in payload:
                        m["rating"] = str(payload["rating"]).strip().upper()[:10]
                    if "day_time" in payload:
                        m["day_time"] = str(payload["day_time"]).strip()[:40]
                    if "channel_info" in payload:
                        m["channel_info"] = str(payload["channel_info"]).strip()[:40]
                    if "enabled" in payload:
                        m["enabled"] = bool(payload["enabled"])
                    self._save_unlocked()
                    return dict(m)
            return None

    def delete_custom_message(self, msg_id: str) -> bool:
        with self._lock:
            msgs = list(self._data.get("custom_messages", []))
            updated = [m for m in msgs if m.get("id") != msg_id]
            if len(updated) == len(msgs):
                return False
            self._data["custom_messages"] = updated
            self._save_unlocked()
            return True

    # --- Top-Right Feature Window Slides ---

    def get_right_deck_slides(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("right_deck_slides", []))

    def add_right_deck_slide(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        title = str(payload.get("title", "")).strip() or "FEATURE"
        with self._lock:
            slides = list(self._data.get("right_deck_slides", []))
            slide = {
                "id": f"slide-{uuid.uuid4().hex[:8]}",
                "title": title[:32],
                "subtitle": str(payload.get("subtitle", "")).strip()[:36],
                "theme": str(payload.get("theme", "reel_talk")).strip(),
                "image_url": str(payload.get("image_url", "")).strip(),
                "enabled": bool(payload.get("enabled", True)),
            }
            slides.append(slide)
            self._data["right_deck_slides"] = slides
            self._save_unlocked()
            return slide

    def update_right_deck_slide(self, slide_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            for s in self._data.get("right_deck_slides", []):
                if s.get("id") == slide_id:
                    for k, max_len in (("title", 32), ("subtitle", 36), ("theme", 24), ("image_url", 500)):
                        if k in payload:
                            s[k] = str(payload[k]).strip()[:max_len]
                    if "enabled" in payload:
                        s["enabled"] = bool(payload["enabled"])
                    self._save_unlocked()
                    return dict(s)
            return None

    def delete_right_deck_slide(self, slide_id: str) -> bool:
        with self._lock:
            slides = list(self._data.get("right_deck_slides", []))
            updated = [s for s in slides if s.get("id") != slide_id]
            if len(updated) == len(slides):
                return False
            self._data["right_deck_slides"] = updated
            self._save_unlocked()
            return True

    # --- In-Grid Rolling Messages ---

    def get_grid_messages(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("grid_messages", []))

    def add_grid_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("Message text is required.")
        with self._lock:
            gmsgs = list(self._data.get("grid_messages", []))
            item = {
                "id": f"gmsg-{uuid.uuid4().hex[:8]}",
                "label": (str(payload.get("label", "NOTICE")).strip() or "NOTICE")[:12],
                "text": text[:120],
                "color_style": str(payload.get("color_style", "sky_blue")).strip() or "sky_blue",
                "enabled": bool(payload.get("enabled", True)),
            }
            gmsgs.append(item)
            self._data["grid_messages"] = gmsgs
            self._save_unlocked()
            return item

    def toggle_grid_message(self, gmsg_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        with self._lock:
            for g in self._data.get("grid_messages", []):
                if g.get("id") == gmsg_id:
                    g["enabled"] = bool(enabled)
                    self._save_unlocked()
                    return dict(g)
            return None

    def delete_grid_message(self, gmsg_id: str) -> bool:
        with self._lock:
            gmsgs = list(self._data.get("grid_messages", []))
            updated = [g for g in gmsgs if g.get("id") != gmsg_id]
            if len(updated) == len(gmsgs):
                return False
            self._data["grid_messages"] = updated
            self._save_unlocked()
            return True

    # --- Custom Channels & EPG Source ---

    def get_epg_config(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data.get("epg", {}))

    def update_epg_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            epg = dict(self._data.get("epg", {}))
            if "xmltv_url" in payload:
                epg["xmltv_url"] = str(payload.get("xmltv_url", "")).strip()
            if "use_custom_channels" in payload:
                epg["use_custom_channels"] = bool(payload.get("use_custom_channels", True))
            self._data["epg"] = epg
            self._save_unlocked()
            return dict(epg)

    def get_custom_channels(self) -> List[Dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(self._data.get("custom_channels", [])))

    def add_custom_channel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        number = str(payload.get("number", "")).strip()
        callsign = str(payload.get("callsign", "")).strip().upper()
        if not number or not callsign:
            raise ValueError("Channel number and callsign are required.")
        programs = payload.get("programs", [])
        if not programs:
            # Support quick two-slot creation from the Admin Portal form
            prog1_title = str(payload.get("prog1_title", "")).strip() or f"{callsign} Programming"
            prog1_rating = str(payload.get("prog1_rating", "")).strip().upper()
            prog1_year = str(payload.get("prog1_year", "")).strip()
            prog1_desc = str(payload.get("prog1_desc", "")).strip()
            prog1_dur = int(payload.get("prog1_duration", 60))
            prog1_started_early = bool(payload.get("prog1_started_early", False))

            prog2_title = str(payload.get("prog2_title", "")).strip() or "Paid Programming"
            prog2_rating = str(payload.get("prog2_rating", "")).strip().upper()
            prog2_year = str(payload.get("prog2_year", "")).strip()
            prog2_desc = str(payload.get("prog2_desc", "")).strip()

            offset1 = -30 if prog1_started_early else 0
            dur1 = max(30, prog1_dur + (30 if prog1_started_early else 0))
            programs = [
                {
                    "title": prog1_title[:60],
                    "rating": prog1_rating[:10],
                    "year": prog1_year[:6],
                    "desc": prog1_desc[:50],
                    "offset_min": offset1,
                    "duration_min": dur1,
                },
                {
                    "title": prog2_title[:60],
                    "rating": prog2_rating[:10],
                    "year": prog2_year[:6],
                    "desc": prog2_desc[:50],
                    "offset_min": offset1 + dur1,
                    "duration_min": 90,
                },
            ]

        with self._lock:
            channels = list(self._data.get("custom_channels", []))
            ch = {
                "id": f"ch-{uuid.uuid4().hex[:8]}",
                "number": number[:6],
                "callsign": callsign[:8],
                "color_Style": str(payload.get("color_Style", "navy")).strip() or "navy",
                "enabled": bool(payload.get("enabled", True)),
                "programs": programs,
            }
            channels.append(ch)
            self._data["custom_channels"] = channels
            self._save_unlocked()
            return ch

    def toggle_custom_channel(self, ch_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        with self._lock:
            for ch in self._data.get("custom_channels", []):
                if ch.get("id") == ch_id:
                    ch["enabled"] = bool(enabled)
                    self._save_unlocked()
                    return dict(ch)
            return None

    def delete_custom_channel(self, ch_id: str) -> bool:
        with self._lock:
            channels = list(self._data.get("custom_channels", []))
            updated = [c for c in channels if c.get("id") != ch_id]
            if len(updated) == len(channels):
                return False
            self._data["custom_channels"] = updated
            self._save_unlocked()
            return True

    # --- RSS Feeds (Up to 5) ---

    def get_rss_feeds(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("rss_feeds", []))[: config.MAX_RSS_FEEDS]

    def add_rss_feed(self, name: str, url: str, enabled: bool = True) -> Dict[str, Any]:
        url = url.strip()
        if not url:
            raise ValueError("RSS feed URL is required.")
        with self._lock:
            feeds = list(self._data.get("rss_feeds", []))
            if len(feeds) >= config.MAX_RSS_FEEDS:
                raise ValueError(f"Maximum of {config.MAX_RSS_FEEDS} RSS feeds reached.")
            new_feed = {
                "id": f"feed-{uuid.uuid4().hex[:8]}",
                "name": (name.strip() or f"Feed {len(feeds) + 1}")[:40],
                "url": url,
                "enabled": bool(enabled),
            }
            feeds.append(new_feed)
            self._data["rss_feeds"] = feeds
            self._save_unlocked()
            return new_feed

    def toggle_rss_feed(self, feed_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
        with self._lock:
            for f in self._data.get("rss_feeds", []):
                if f.get("id") == feed_id:
                    f["enabled"] = bool(enabled)
                    self._save_unlocked()
                    return dict(f)
            return None

    def delete_rss_feed(self, feed_id: str) -> bool:
        with self._lock:
            feeds = list(self._data.get("rss_feeds", []))
            updated = [f for f in feeds if f.get("id") != feed_id]
            if len(updated) == len(feeds):
                return False
            self._data["rss_feeds"] = updated
            self._save_unlocked()
            return True

    # --- Radio Station Presets & Audio Mode ---

    def get_radio_presets(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._data.get("radio_presets", []))

    def add_radio_preset(self, name: str, url: str, activate: bool = False) -> Dict[str, Any]:
        url = url.strip()
        if not url:
            raise ValueError("Radio stream URL is required.")
        with self._lock:
            presets = list(self._data.get("radio_presets", []))
            preset = {
                "id": f"radio-{uuid.uuid4().hex[:8]}",
                "name": (name.strip() or f"Station {len(presets) + 1}")[:50],
                "url": url,
            }
            presets.append(preset)
            self._data["radio_presets"] = presets
            if activate or not self._data.get("active_radio_id"):
                self._data["active_radio_id"] = preset["id"]
                self._data["audio_mode"] = "stream"
            self._save_unlocked()
            return preset

    def delete_radio_preset(self, preset_id: str) -> bool:
        with self._lock:
            presets = list(self._data.get("radio_presets", []))
            updated = [p for p in presets if p.get("id") != preset_id]
            if len(updated) == len(presets):
                return False
            self._data["radio_presets"] = updated
            if self._data.get("active_radio_id") == preset_id:
                self._data["active_radio_id"] = updated[0]["id"] if updated else None
            self._save_unlocked()
            return True

    def set_audio_selection(self, audio_mode: str, active_radio_id: Optional[str] = None) -> Dict[str, Any]:
        mode = audio_mode.strip().lower()
        if mode not in ("stream", "hum", "silent"):
            raise ValueError("audio_mode must be 'stream', 'hum', or 'silent'")
        with self._lock:
            self._data["audio_mode"] = mode
            if active_radio_id is not None:
                self._data["active_radio_id"] = active_radio_id
            self._save_unlocked()
            return self.get_active_audio()

    def get_active_audio(self) -> Dict[str, Any]:
        with self._lock:
            mode = self._data.get("audio_mode", "hum")
            active_id = self._data.get("active_radio_id")
            presets = self._data.get("radio_presets", [])
            active_preset = next((p for p in presets if p.get("id") == active_id), None)
            if active_preset is None and presets:
                active_preset = presets[0]
            return {
                "audio_mode": mode,
                "active_radio_id": active_preset["id"] if active_preset else None,
                "active_radio_name": active_preset["name"] if active_preset else None,
                "active_radio_url": active_preset["url"] if active_preset else "",
            }

    # --- Display & CRT Settings ---

    def get_display(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data.get("display", {}))

    def update_display(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            disp = dict(self._data.get("display", {}))
            for str_key in ("channel_number", "channel_name"):
                if str_key in updates and updates[str_key] is not None:
                    disp[str_key] = str(updates[str_key]).strip()[:32]
            for float_key in ("scroll_speed", "promo_duration"):
                if float_key in updates and updates[float_key] is not None:
                    disp[float_key] = max(2.0, float(updates[float_key]))
            for bool_key in (
                "include_rss_in_topleft",
                "show_grid_messages",
                "time_format_12h",
                "scanlines",
                "crt_noise",
                "crt_vignette",
            ):
                if bool_key in updates and updates[bool_key] is not None:
                    disp[bool_key] = bool(updates[bool_key])
            self._data["display"] = disp
            self._save_unlocked()
            return dict(disp)


settings_store = SettingsStore()
