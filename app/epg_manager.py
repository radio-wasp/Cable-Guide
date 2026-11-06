import html
import io
import logging
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from PIL import Image

from app import config
from app.settings_store import settings_store

logger = logging.getLogger("cable-guide.epg")


@dataclass
class ProgramBlock:
    title: str
    rating: str = ""
    year: str = ""
    desc: str = ""
    offset_min: int = 0       # Minutes relative to current 30-min window start (can be negative if started earlier)
    duration_min: int = 60    # Total duration in minutes


@dataclass
class GuideRow:
    row_type: str             # "channel" or "message"
    channel_number: str = ""
    callsign: str = ""
    color_style: str = "navy"  # "sky_blue", "crimson", "navy"
    programs: List[ProgramBlock] = field(default_factory=list)
    message_text: str = ""


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_xmltv_dt(raw: str) -> Optional[datetime]:
    """Parse XMLTV timestamp like '20261105200000 -0400' or '20261105200000'."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        if " " in raw:
            dt_part, tz_part = raw.split(" ", 1)
            dt_part = dt_part[:14]
            tz_part = tz_part.strip()
            if len(tz_part) == 5 and (tz_part[0] in "+-"):
                return datetime.strptime(f"{dt_part} {tz_part}", "%Y%m%d%H%M%S %z")
        return datetime.strptime(raw[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _current_window_start_local() -> datetime:
    now = datetime.now().astimezone()
    floored_min = 30 if now.minute >= 30 else 0
    return now.replace(minute=floored_min, second=0, microsecond=0)


class EPGAndFeedManager:
    """
    Manages:
    - Live XMLTV parsing + Custom Prevue Channel rows + In-grid rolling message banners
    - Optional RSS feed fetching for Top-Left bulletin cards
    - Cached remote images for Top-Right feature slides
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._xmltv_rows: List[GuideRow] = []
        self._xmltv_error: Optional[str] = None
        self._xmltv_channel_count: int = 0
        self._rss_cards: List[Dict[str, Any]] = []
        self._feed_stats: List[Dict[str, Any]] = []
        self._slide_images: Dict[str, Image.Image] = {}
        self._last_refresh: Optional[str] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        self.refresh_now()
        while self._running:
            interval_sec = max(60, config.REFRESH_INTERVAL_MINUTES * 60)
            for _ in range(interval_sec):
                if not self._running:
                    return
                time.sleep(1)
            self.refresh_now()

    def refresh_now(self) -> Dict[str, Any]:
        self._refresh_xmltv()
        self._refresh_rss()
        self._refresh_slide_images()
        with self._lock:
            self._last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self.get_status()

    def _refresh_xmltv(self) -> None:
        epg_cfg = settings_store.get_epg_config()
        xmltv_url = str(epg_cfg.get("xmltv_url", "")).strip()
        if not xmltv_url:
            with self._lock:
                self._xmltv_rows = []
                self._xmltv_channel_count = 0
                self._xmltv_error = None
            return

        try:
            req = urllib.request.Request(
                xmltv_url,
                headers={"User-Agent": "CableGuideHLS/2.0 (Prevue Channel Emulator)"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_bytes = resp.read()
            root = ET.fromstring(raw_bytes)
            win_start = _current_window_start_local()
            win_end = win_start + timedelta(minutes=90)

            channels_by_id: Dict[str, Dict[str, str]] = {}
            for idx, ch_el in enumerate(root.findall(".//channel")):
                ch_id = ch_el.attrib.get("id", f"ch-{idx+1}")
                disp_names = [
                    (dn.text or "").strip()
                    for dn in ch_el.findall("display-name")
                    if (dn.text or "").strip()
                ]
                callsign = disp_names[0] if disp_names else ch_id
                chno = str(idx + 1)
                for dn in disp_names:
                    if dn.isdigit():
                        chno = dn
                        break
                callsign_short = re.sub(r"[^A-Z0-9 ]", "", callsign.upper()).strip()[:7] or callsign.upper()[:6]
                channels_by_id[ch_id] = {"number": chno[:5], "callsign": callsign_short}

            progs_by_ch: Dict[str, List[ProgramBlock]] = {cid: [] for cid in channels_by_id}
            for pr_el in root.findall(".//programme"):
                cid = pr_el.attrib.get("channel", "")
                if cid not in progs_by_ch:
                    continue
                start_dt = _parse_xmltv_dt(pr_el.attrib.get("start", ""))
                stop_dt = _parse_xmltv_dt(pr_el.attrib.get("stop", ""))
                if not start_dt or not stop_dt:
                    continue
                start_local = start_dt.astimezone(win_start.tzinfo)
                stop_local = stop_dt.astimezone(win_start.tzinfo)
                if stop_local <= win_start or start_local >= win_end:
                    continue

                title = _strip_html(pr_el.findtext("title") or "Programming")
                desc = _strip_html(pr_el.findtext("desc") or "")
                rating = _strip_html(pr_el.findtext("rating/value") or "")
                year = _strip_html(pr_el.findtext("date") or "")[:4]

                offset_min = int(round((start_local - win_start).total_seconds() / 60.0))
                dur_min = max(15, int(round((stop_local - start_local).total_seconds() / 60.0)))
                progs_by_ch[cid].append(
                    ProgramBlock(
                        title=title,
                        rating=rating,
                        year=year,
                        desc=desc[:45],
                        offset_min=offset_min,
                        duration_min=dur_min,
                    )
                )

            rows: List[GuideRow] = []
            for cid, ch_meta in channels_by_id.items():
                plist = sorted(progs_by_ch.get(cid, []), key=lambda p: p.offset_min)
                if not plist:
                    plist = [
                        ProgramBlock(
                            title=f"{ch_meta['callsign']} Programming",
                            offset_min=0,
                            duration_min=90,
                        )
                    ]
                cs_upper = ch_meta["callsign"].upper()
                if any(k in cs_upper for k in ("HBO", "MAX", "SHOW", "TMC", "STARZ", "ENC", "MOVIE")):
                    cstyle = "crimson"
                elif any(k in cs_upper for k in ("PPV", "HOT", "ASN", "ESPN", "USA")):
                    cstyle = "sky_blue"
                else:
                    cstyle = "navy"

                rows.append(
                    GuideRow(
                        row_type="channel",
                        channel_number=ch_meta["number"],
                        callsign=ch_meta["callsign"],
                        color_style=cstyle,
                        programs=plist,
                    )
                )

            with self._lock:
                self._xmltv_rows = rows
                self._xmltv_channel_count = len(rows)
                self._xmltv_error = None
            logger.info("Loaded %d channels from XMLTV (%s)", len(rows), xmltv_url)
        except Exception as exc:
            logger.warning("Failed to fetch XMLTV from %s: %s", xmltv_url, exc)
            with self._lock:
                self._xmltv_error = str(exc)

    def _refresh_rss(self) -> None:
        feeds = settings_store.get_rss_feeds()
        cards: List[Dict[str, Any]] = []
        stats: List[Dict[str, Any]] = []

        for f in feeds:
            fid = f.get("id", "")
            fname = f.get("name", "RSS Feed")
            furl = f.get("url", "").strip()
            enabled = bool(f.get("enabled", True))
            if not enabled or not furl:
                stats.append({"id": fid, "name": fname, "url": furl, "enabled": enabled, "item_count": 0, "error": None})
                continue

            try:
                req = urllib.request.Request(
                    furl,
                    headers={"User-Agent": "CableGuideHLS/2.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    xml_bytes = resp.read()
                root = ET.fromstring(xml_bytes)
                items = root.findall(".//item")
                if not items:
                    items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

                count = 0
                for item_el in items[: config.MAX_ITEMS_PER_FEED]:
                    title = (
                        item_el.findtext("title")
                        or item_el.findtext("{http://www.w3.org/2005/Atom}title")
                        or ""
                    )
                    title = _strip_html(title)
                    if not title:
                        continue
                    cards.append({
                        "id": f"rss-{fid}-{count}",
                        "network": fname[:28],
                        "title": title[:68],
                        "rating": "NEWS",
                        "day_time": datetime.now().strftime("%A"),
                        "channel_info": f"CH {settings_store.get_display().get('channel_number', '03')} HEADLINE",
                        "is_rss": True,
                    })
                    count += 1
                stats.append({"id": fid, "name": fname, "url": furl, "enabled": True, "item_count": count, "error": None})
            except Exception as exc:
                stats.append({"id": fid, "name": fname, "url": furl, "enabled": True, "item_count": 0, "error": str(exc)})

        with self._lock:
            self._rss_cards = cards
            self._feed_stats = stats

    def _refresh_slide_images(self) -> None:
        slides = settings_store.get_right_deck_slides()
        for s in slides:
            url = str(s.get("image_url", "")).strip()
            if not url:
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "CableGuideHLS/2.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    img_bytes = resp.read()
                im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                with self._lock:
                    self._slide_images[url] = im
            except Exception as exc:
                logger.debug("Could not load slide image %s: %s", url, exc)

    def get_cached_slide_image(self, url: str) -> Optional[Image.Image]:
        with self._lock:
            return self._slide_images.get(url)

    def get_rolling_rows(self) -> List[GuideRow]:
        """
        Returns the ordered list of GuideRow items (channels + interleaved custom in-grid messages)
        for the bottom rolling Prevue grid.
        """
        epg_cfg = settings_store.get_epg_config()
        disp = settings_store.get_display()
        channel_rows: List[GuideRow] = []

        if epg_cfg.get("use_custom_channels", True):
            for ch in settings_store.get_custom_channels():
                if not ch.get("enabled", True):
                    continue
                plist: List[ProgramBlock] = []
                for p in ch.get("programs", []):
                    plist.append(
                        ProgramBlock(
                            title=str(p.get("title", "Programming")),
                            rating=str(p.get("rating", "")),
                            year=str(p.get("year", "")),
                            desc=str(p.get("desc", "")),
                            offset_min=int(p.get("offset_min", 0)),
                            duration_min=max(15, int(p.get("duration_min", 60))),
                        )
                    )
                channel_rows.append(
                    GuideRow(
                        row_type="channel",
                        channel_number=str(ch.get("number", "")),
                        callsign=str(ch.get("callsign", "")),
                        color_style=str(ch.get("color_Style", "navy")),
                        programs=plist,
                    )
                )

        with self._lock:
            if self._xmltv_rows:
                channel_rows.extend(self._xmltv_rows)

        if not channel_rows:
            channel_rows.append(
                GuideRow(
                    row_type="channel",
                    channel_number="03",
                    callsign="PREVUE",
                    color_style="sky_blue",
                    programs=[ProgramBlock(title="Prevue Channel Guide", offset_min=0, duration_min=90)],
                )
            )

        # Interleave enabled in-grid custom message rows every 4 channels
        if not disp.get("show_grid_messages", True):
            return channel_rows

        enabled_gmsgs = [g for g in settings_store.get_grid_messages() if g.get("enabled", True)]
        if not enabled_gmsgs:
            return channel_rows

        combined: List[GuideRow] = []
        g_idx = 0
        for i, row in enumerate(channel_rows):
            combined.append(row)
            if (i + 1) % 4 == 0 and enabled_gmsgs:
                gm = enabled_gmsgs[g_idx % len(enabled_gmsgs)]
                g_idx += 1
                combined.append(
                    GuideRow(
                        row_type="message",
                        channel_number="",
                        callsign=str(gm.get("label", "NOTICE")),
                        color_style=str(gm.get("color_style", "sky_blue")),
                        message_text=str(gm.get("text", "")),
                    )
                )
        return combined

    def get_topleft_cards(self) -> List[Dict[str, Any]]:
        """
        Returns the active rotation of Top-Left Prevue promo/bulletin cards.
        """
        custom = [m for m in settings_store.get_custom_messages() if m.get("enabled", True)]
        disp = settings_store.get_display()
        if disp.get("include_rss_in_topleft", False):
            with self._lock:
                rss = list(self._rss_cards)
            if rss:
                # Interleave custom messages and RSS headlines
                merged: List[Dict[str, Any]] = []
                max_len = max(len(custom), len(rss))
                for i in range(max_len):
                    if i < len(custom):
                        merged.append(custom[i])
                    if i < len(rss):
                        merged.append(rss[i])
                return merged
        if custom:
            return custom
        return [
            {
                "id": "fallback",
                "network": "Prevue Guide",
                "title": '"Your Cable Program Guide"',
                "rating": "TV-G",
                "day_time": datetime.now().strftime("%A"),
                "channel_info": f"Channel {disp.get('channel_number', '03')}",
            }
        ]

    def get_topright_slides(self) -> List[Dict[str, Any]]:
        slides = [s for s in settings_store.get_right_deck_slides() if s.get("enabled", True)]
        if slides:
            return slides
        return [
            {
                "id": "default-slide",
                "title": "REEL TALK",
                "subtitle": "DAVID SPADE",
                "theme": "reel_talk",
                "image_url": "",
            }
        ]

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "last_refresh": self._last_refresh,
                "xmltv_channels": self._xmltv_channel_count,
                "xmltv_error": self._xmltv_error,
                "total_grid_rows": len(self.get_rolling_rows()),
                "topleft_cards_count": len(self.get_topleft_cards()),
                "topright_slides_count": len(self.get_topright_slides()),
                "feeds": list(self._feed_stats),
            }


epg_manager = EPGAndFeedManager()
