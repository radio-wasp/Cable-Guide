import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from xml.sax.saxutils import escape

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.epg_manager import epg_manager
from app.renderer import renderer
from app.settings_store import settings_store
from app.streamer import stream_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cable-guide.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Vintage Cable TV Rolling Guide (Prevue HLS)...")
    epg_manager.start()
    stream_manager.start()
    yield
    logger.info("Shutting down Vintage Cable TV Rolling Guide...")
    stream_manager.stop()
    epg_manager.stop()


app = FastAPI(
    title="Vintage Cable TV Rolling Guide (Prevue HLS)",
    description="1990s Prevue Channel style Rolling TV Guide with customizable promo messages, XMLTV support & live radio",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _get_base_url(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", f"localhost:{config.PORT}"))
    return f"{scheme}://{host}"


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    base_url = _get_base_url(request)
    disp = settings_store.get_display()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "channel_number": disp.get("channel_number", config.CHANNEL_NUMBER),
            "channel_name": disp.get("channel_name", config.CHANNEL_NAME),
            "base_url": base_url,
            "hls_url": f"{base_url}/hls/stream.m3u8",
            "m3u_url": f"{base_url}/playlist.m3u",
            "epg_url": f"{base_url}/epg.xml",
            "ts_url": f"{base_url}/live.ts",
            "max_feeds": config.MAX_RSS_FEEDS,
        },
    )


async def _wait_for_m3u8(timeout_sec: float = 8.0) -> str:
    m3u8_path = os.path.join(config.HLS_DIR, "stream.m3u8")
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        if os.path.exists(m3u8_path) and os.path.getsize(m3u8_path) > 0:
            return m3u8_path
        await asyncio.sleep(0.2)
    if not os.path.exists(m3u8_path):
        raise HTTPException(status_code=503, detail="HLS stream is warming up, please retry in a moment.")
    return m3u8_path


@app.get("/hls/stream.m3u8")
async def get_hls_manifest():
    m3u8_path = await _wait_for_m3u8()
    return FileResponse(
        m3u8_path,
        media_type="application/vnd.apple.mpegurl",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/stream.m3u8")
async def get_root_hls_manifest():
    m3u8_path = await _wait_for_m3u8()
    with open(m3u8_path, "r", encoding="utf-8") as f:
        content = f.read()
    rewritten = "\n".join(
        f"/hls/{line}" if line.strip().endswith(".ts") and not line.strip().startswith("/") else line
        for line in content.splitlines()
    ) + "\n"
    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/hls/{segment_name}")
async def get_hls_segment(segment_name: str):
    if not segment_name.endswith(".ts") or "/" in segment_name or ".." in segment_name:
        raise HTTPException(status_code=404, detail="Invalid segment")
    seg_path = os.path.join(config.HLS_DIR, segment_name)
    if not os.path.exists(seg_path):
        raise HTTPException(status_code=404, detail="Segment not found")
    return FileResponse(
        seg_path,
        media_type="video/mp2t",
        headers={"Cache-Control": "public, max-age=10"},
    )


@app.get("/live.ts")
@app.get("/stream")
async def get_live_mpegts():
    return StreamingResponse(
        stream_manager.iter_live_mpegts(),
        media_type="video/mp2t",
        headers=NO_CACHE_HEADERS,
    )


@app.get("/playlist.m3u")
async def get_m3u_playlist(request: Request):
    base_url = _get_base_url(request)
    disp = settings_store.get_display()
    chno = disp.get("channel_number", config.CHANNEL_NUMBER)
    name = disp.get("channel_name", config.CHANNEL_NAME)
    ch_id = f"cable-guide-{chno}"
    m3u_content = (
        f'#EXTM3U url-tvg="{base_url}/epg.xml"\n'
        f'#EXTINF:-1 tvg-id="{ch_id}" tvg-chno="{chno}" tvg-name="{name}" '
        f'tvg-logo="{base_url}/preview.png" group-title="Program Guides",{name}\n'
        f"{base_url}/hls/stream.m3u8\n"
    )
    return Response(content=m3u_content, media_type="audio/x-mpegurl")


@app.get("/epg.xml")
async def get_epg_xml(request: Request):
    base_url = _get_base_url(request)
    disp = settings_store.get_display()
    chno = disp.get("channel_number", config.CHANNEL_NUMBER)
    name = disp.get("channel_name", config.CHANNEL_NAME)
    ch_id = f"cable-guide-{chno}"
    now = datetime.now(timezone.utc)
    start_base = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tv generator-info-name="CableGuideHLS">',
        f'  <channel id="{escape(ch_id)}">',
        f'    <display-name>{escape(name)}</display-name>',
        f'    <display-name>{escape(chno)}</display-name>',
        f'    <icon src="{escape(base_url)}/preview.png" />',
        '  </channel>',
    ]

    for h in range(26):
        slot_start = start_base + timedelta(hours=h)
        slot_end = slot_start + timedelta(hours=1)
        s_str = slot_start.strftime("%Y%m%d%H%M%S +0000")
        e_str = slot_end.strftime("%Y%m%d%H%M%S +0000")
        lines.extend([
            f'  <programme start="{s_str}" stop="{e_str}" channel="{escape(ch_id)}">',
            f'    <title lang="en">{escape(name)}</title>',
            '    <desc lang="en">24-hour rolling cable TV program guide with customizable '
            'channel spotlights, announcements, and background radio.</desc>',
            '    <category lang="en">Guide</category>',
            '  </programme>',
        ])

    lines.append("</tv>")
    return Response(content="\n".join(lines), media_type="application/xml")


@app.get("/preview.png")
async def get_preview_png():
    png_bytes = renderer.render_png_bytes()
    return Response(content=png_bytes, media_type="image/png", headers=NO_CACHE_HEADERS)


# =====================================================================
# ADMIN PORTAL REST API
# =====================================================================

@app.get("/api/status")
async def api_status():
    return {
        "stream": stream_manager.get_status(),
        "epg_status": epg_manager.get_status(),
        "settings": settings_store.get_all(),
        "active_audio": settings_store.get_active_audio(),
    }


@app.post("/api/refresh")
async def api_refresh():
    st = await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "epg_status": st}


# --- Top-Left Custom Promo & Bulletin Messages ---

@app.post("/api/messages")
async def api_add_message(payload: Dict[str, Any] = Body(...)):
    try:
        msg = settings_store.add_custom_message(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "message": msg, "custom_messages": settings_store.get_custom_messages()}


@app.patch("/api/messages/{msg_id}")
async def api_update_message(msg_id: str, payload: Dict[str, Any] = Body(...)):
    updated = settings_store.update_custom_message(msg_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True, "message": updated, "custom_messages": settings_store.get_custom_messages()}


@app.delete("/api/messages/{msg_id}")
async def api_delete_message(msg_id: str):
    if not settings_store.delete_custom_message(msg_id):
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True, "custom_messages": settings_store.get_custom_messages()}


# --- Top-Right Feature Window Slides ---

@app.post("/api/slides")
async def api_add_slide(payload: Dict[str, Any] = Body(...)):
    slide = settings_store.add_right_deck_slide(payload)
    await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "slide": slide, "right_deck_slides": settings_store.get_right_deck_slides()}


@app.patch("/api/slides/{slide_id}")
async def api_update_slide(slide_id: str, payload: Dict[str, Any] = Body(...)):
    updated = settings_store.update_right_deck_slide(slide_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Slide not found")
    await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "slide": updated, "right_deck_slides": settings_store.get_right_deck_slides()}


@app.delete("/api/slides/{slide_id}")
async def api_delete_slide(slide_id: str):
    if not settings_store.delete_right_deck_slide(slide_id):
        raise HTTPException(status_code=404, detail="Slide not found")
    return {"ok": True, "right_deck_slides": settings_store.get_right_deck_slides()}


# --- In-Grid Rolling Messages ---

@app.post("/api/grid-messages")
async def api_add_grid_message(payload: Dict[str, Any] = Body(...)):
    try:
        item = settings_store.add_grid_message(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "grid_message": item, "grid_messages": settings_store.get_grid_messages()}


@app.patch("/api/grid-messages/{gmsg_id}")
async def api_toggle_grid_message(gmsg_id: str, payload: Dict[str, Any] = Body(...)):
    updated = settings_store.toggle_grid_message(gmsg_id, bool(payload.get("enabled", True)))
    if not updated:
        raise HTTPException(status_code=404, detail="Grid message not found")
    return {"ok": True, "grid_message": updated, "grid_messages": settings_store.get_grid_messages()}


@app.delete("/api/grid-messages/{gmsg_id}")
async def api_delete_grid_message(gmsg_id: str):
    if not settings_store.delete_grid_message(gmsg_id):
        raise HTTPException(status_code=404, detail="Grid message not found")
    return {"ok": True, "grid_messages": settings_store.get_grid_messages()}


# --- Custom Channels & External XMLTV EPG ---

@app.put("/api/epg-config")
async def api_update_epg_config(payload: Dict[str, Any] = Body(...)):
    cfg = settings_store.update_epg_config(payload)
    st = await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "epg": cfg, "epg_status": st}


@app.post("/api/channels")
async def api_add_channel(payload: Dict[str, Any] = Body(...)):
    try:
        ch = settings_store.add_custom_channel(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "channel": ch, "custom_channels": settings_store.get_custom_channels()}


@app.patch("/api/channels/{ch_id}")
async def api_toggle_channel(ch_id: str, payload: Dict[str, Any] = Body(...)):
    updated = settings_store.toggle_custom_channel(ch_id, bool(payload.get("enabled", True)))
    if not updated:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True, "channel": updated, "custom_channels": settings_store.get_custom_channels()}


@app.delete("/api/channels/{ch_id}")
async def api_delete_channel(ch_id: str):
    if not settings_store.delete_custom_channel(ch_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"ok": True, "custom_channels": settings_store.get_custom_channels()}


# --- RSS Feeds (Up to 5) ---

@app.post("/api/feeds")
async def api_add_feed(payload: Dict[str, Any] = Body(...)):
    try:
        new_feed = settings_store.add_rss_feed(
            name=str(payload.get("name", "")),
            url=str(payload.get("url", "")),
            enabled=bool(payload.get("enabled", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    st = await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "feed": new_feed, "epg_status": st}


@app.patch("/api/feeds/{feed_id}")
async def api_toggle_feed(feed_id: str, payload: Dict[str, Any] = Body(...)):
    updated = settings_store.toggle_rss_feed(feed_id, bool(payload.get("enabled", True)))
    if not updated:
        raise HTTPException(status_code=404, detail="Feed not found")
    st = await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "feed": updated, "epg_status": st}


@app.delete("/api/feeds/{feed_id}")
async def api_delete_feed(feed_id: str):
    if not settings_store.delete_rss_feed(feed_id):
        raise HTTPException(status_code=404, detail="Feed not found")
    st = await asyncio.to_thread(epg_manager.refresh_now)
    return {"ok": True, "epg_status": st}


# --- Radio Station Presets & Audio Control ---

@app.post("/api/radio/presets")
async def api_add_radio_preset(payload: Dict[str, Any] = Body(...)):
    activate = bool(payload.get("activate", True))
    try:
        preset = settings_store.add_radio_preset(
            name=str(payload.get("name", "")),
            url=str(payload.get("url", "")),
            activate=activate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if activate:
        stream_manager.restart_encoder()
    return {
        "ok": True,
        "preset": preset,
        "radio_presets": settings_store.get_radio_presets(),
        "active_audio": settings_store.get_active_audio(),
    }


@app.delete("/api/radio/presets/{preset_id}")
async def api_delete_radio_preset(preset_id: str):
    prev_active = settings_store.get_active_audio().get("active_radio_id")
    if not settings_store.delete_radio_preset(preset_id):
        raise HTTPException(status_code=404, detail="Preset not found")
    if prev_active == preset_id:
        stream_manager.restart_encoder()
    return {
        "ok": True,
        "radio_presets": settings_store.get_radio_presets(),
        "active_audio": settings_store.get_active_audio(),
    }


@app.post("/api/radio/select")
async def api_select_radio(payload: Dict[str, Any] = Body(...)):
    audio_mode = str(payload.get("audio_mode", "stream"))
    active_radio_id = payload.get("active_radio_id")
    try:
        active = settings_store.set_audio_selection(audio_mode, active_radio_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stream_manager.restart_encoder()
    return {"ok": True, "active_audio": active}


# --- Display & Scroll Settings ---

@app.put("/api/display")
async def api_update_display(payload: Dict[str, Any] = Body(...)):
    updated = settings_store.update_display(payload)
    return {"ok": True, "display": updated}


@app.get("/health")
async def health():
    return {"status": "ok", "hls_ready": stream_manager.is_ready()}
