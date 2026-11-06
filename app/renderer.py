import io
import logging
import math
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app import config
from app.epg_manager import GuideRow, ProgramBlock, epg_manager
from app.settings_store import settings_store

logger = logging.getLogger("cable-guide.renderer")

ColorRGB = Tuple[int, int, int]

# Bold sans-serif broadcast fonts (Prevue Guide uses condensed/bold sans-serif throughout)
SANS_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

# Palette definitions for 3D beveled program bars (matching reference capture)
BAR_PALETTES: Dict[str, Dict[str, ColorRGB]] = {
    "sky_blue": {
        "face_top": (48, 136, 212),
        "face_bot": (32, 108, 184),
        "bevel_light": (122, 196, 252),
        "bevel_dark": (14, 54, 108),
        "border": (6, 18, 42),
    },
    "crimson": {
        "face_top": (112, 36, 48),
        "face_bot": (88, 24, 36),
        "bevel_light": (176, 88, 102),
        "bevel_dark": (46, 8, 16),
        "border": (18, 4, 8),
    },
    "navy": {
        "face_top": (42, 68, 128),
        "face_bot": (28, 48, 98),
        "bevel_light": (92, 124, 188),
        "bevel_dark": (14, 24, 58),
        "border": (6, 10, 28),
    },
    "teal": {
        "face_top": (26, 112, 118),
        "face_bot": (18, 84, 92),
        "bevel_light": (88, 178, 184),
        "bevel_dark": (8, 44, 50),
        "border": (4, 18, 22),
    },
}


def _load_font(candidates: List[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


class PrevueGuideRenderer:
    """
    Renders 24-bit RGB frames replicating the 1996-1999 Prevue Channel / Rolling TV Guide:
    - Upper-Left: Cobalt-navy promo/bulletin quadrant (Cinemax / "Black Sheep" [PG-13] / Wednesday / Channel 14)
    - Upper-Right: Quarter-screen feature window with gold lower-third overlay (REEL TALK / DAVID SPADE)
    - Middle Bar: 3D beveled slate-blue clock (10:45:11) + three 30-min time slot headers (10:30 AM | 11:00 AM | 11:30 AM)
    - Bottom Half: Smoothly scrolling 3D beveled channel grid with left/right continuation chevrons (<< / >>)
      and inline boxed movie/TV rating badges ([PG-13], [PG], [R]).
    """

    def __init__(self, width: int = config.WIDTH, height: int = config.HEIGHT) -> None:
        self.width = width
        self.height = height
        self.scale = height / 720.0

        # Layout coordinates (at 1280x720)
        self.upper_h = self._s(336)           # Top split deck height (0..336)
        self.split_x = self._s(610)           # Split X between Top-Left and Top-Right
        self.timebar_y = self.upper_h         # 336
        self.timebar_h = self._s(64)          # 336..400
        self.grid_y = self.timebar_y + self.timebar_h  # 400
        self.grid_h = self.height - self.grid_y        # 320
        self.chan_col_w = self._s(218)        # Left column width for clock & channel number/callsign
        self.prog_area_w = self.width - self.chan_col_w  # 1062px for 90 minutes
        self.slot_w = self.prog_area_w // 3   # 354px per 30-min column
        self.row_h = self._s(92)              # ~3.48 rows visible in 320px grid

        # Fonts
        self.font_promo_line = _load_font(SANS_BOLD_CANDIDATES, self._s(36))
        self.font_promo_badge = _load_font(SANS_BOLD_CANDIDATES, self._s(22))
        self.font_lt_gold = _load_font(SANS_BOLD_CANDIDATES, self._s(44))
        self.font_lt_sub = _load_font(SANS_BOLD_CANDIDATES, self._s(27))
        self.font_clock = _load_font(SANS_BOLD_CANDIDATES, self._s(35))
        self.font_timeslot = _load_font(SANS_BOLD_CANDIDATES, self._s(36))
        self.font_chan = _load_font(SANS_BOLD_CANDIDATES, self._s(34))
        self.font_prog = _load_font(SANS_BOLD_CANDIDATES, self._s(33))
        self.font_badge = _load_font(SANS_BOLD_CANDIDATES, self._s(21))

        # Pre-rendered static upper-left cobalt background & procedural upper-right backdrops
        self._topleft_bg = self._build_topleft_bg()
        self._right_backdrops: Dict[str, Image.Image] = {
            "reel_talk": self._build_reel_talk_backdrop(),
            "cinema": self._build_cinema_backdrop(),
            "studio": self._build_studio_backdrop(),
        }

        # CRT scanline & vignette masks
        self._scanline_mask = self._build_mask(scanlines=True, vignette=True)
        self._scanline_only_mask = self._build_mask(scanlines=True, vignette=False)
        self._vignette_only_mask = self._build_mask(scanlines=False, vignette=True)

        # Pre-rendered analog RF noise frames
        self._noise_frames = self._build_noise_frames(count=8)
        self._noise_idx = 0

        self._start_time = time.monotonic()

    def _s(self, val: float) -> int:
        return int(round(val * self.scale))

    def _draw_condensed_text(
        self,
        target: Image.Image,
        pos: Tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: ColorRGB = (242, 246, 255),
        shadow_fill: ColorRGB = (6, 8, 18),
        shadow_offset: Tuple[int, int] = (3, 3),
        stretch_x: float = 0.88,
    ) -> int:
        """
        Draws bold condensed Prevue-style text with a crisp dark drop shadow.
        Returns the drawn width in pixels.
        """
        if not text:
            return 0
        dummy = ImageDraw.Draw(target)
        bb = dummy.textbbox((0, 0), text, font=font)
        raw_w = max(1, bb[2] - bb[0] + self._s(10))
        raw_h = max(1, bb[3] - bb[1] + self._s(16))
        pad = self._s(8)
        lw = raw_w + pad * 2
        lh = raw_h + pad * 2

        mask = Image.new("L", (lw, lh), color=0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.text((pad, pad), text, fill=255, font=font)

        if abs(stretch_x - 1.0) > 0.01:
            sw = max(1, int(round(lw * stretch_x)))
            mask = mask.resize((sw, lh), Image.BILINEAR)

        x, y = pos
        sx, sy = shadow_offset
        pad_x = int(round(pad * stretch_x))
        target.paste(shadow_fill, (x - pad_x + sx, y - pad + sy), mask)
        target.paste(fill, (x - pad_x, y - pad), mask)
        return int(round((bb[2] - bb[0]) * stretch_x))

    def _measure_condensed(self, text: str, font: ImageFont.FreeTypeFont, stretch_x: float = 0.88) -> int:
        if not text:
            return 0
        dummy = Image.new("L", (8, 8))
        ddraw = ImageDraw.Draw(dummy)
        bb = ddraw.textbbox((0, 0), text, font=font)
        return int(round((bb[2] - bb[0]) * stretch_x))

    def _draw_rating_badge(
        self,
        target: Image.Image,
        pos: Tuple[int, int],
        rating: str,
        color: ColorRGB = (242, 246, 255),
        bg_fill: Optional[ColorRGB] = (18, 28, 58),
    ) -> int:
        """
        Draws the authentic Prevue Guide boxed rating badge (e.g. [PG-13], [PG], [R])
        inline with program or promo titles. Returns badge width.
        """
        rating = rating.strip().upper()
        if not rating:
            return 0
        text_w = self._measure_condensed(rating, self.font_badge, stretch_x=0.84)
        pad_x = self._s(6)
        bw = text_w + pad_x * 2
        bh = self._s(26)
        x, y = pos

        draw = ImageDraw.Draw(target)
        # Drop shadow
        sh_off = self._s(3)
        draw.rectangle([x + sh_off, y + sh_off, x + bw + sh_off, y + bh + sh_off], fill=(6, 8, 18))
        if bg_fill:
            draw.rectangle([x, y, x + bw, y + bh], fill=bg_fill, outline=color, width=2)
        else:
            draw.rectangle([x, y, x + bw, y + bh], outline=color, width=2)

        self._draw_condensed_text(
            target,
            (x + pad_x, y + self._s(1)),
            rating,
            self.font_badge,
            fill=color,
            shadow_fill=(6, 8, 18),
            shadow_offset=(self._s(2), self._s(2)),
            stretch_x=0.84,
        )
        return bw

    def _build_topleft_bg(self) -> Image.Image:
        """
        Builds the Top-Left Prevue cobalt-navy background with subtle vertical
        ribbon shading matching the reference screenshot.
        """
        W, H = self.split_x, self.upper_h
        img = Image.new("RGB", (W, H), color=(12, 24, 108))
        draw = ImageDraw.Draw(img)
        for x in range(W):
            # Subtle vertical specular bands like the Prevue Amiga copper-list gradient
            nx = x / float(max(1, W))
            wave = math.sin(nx * math.pi * 3.2) * 10 + (1.0 - nx) * 14
            for y in range(H):
                ny = y / float(max(1, H))
                r = int(max(6, min(38, 10 + wave * 0.4 - ny * 6)))
                g = int(max(14, min(64, 24 + wave * 0.8 - ny * 10)))
                b = int(max(68, min(168, 112 + wave * 2.1 - ny * 26)))
                draw.point((x, y), fill=(r, g, b))
        # Dark right divider edge
        draw.rectangle([W - self._s(4), 0, W - 1, H], fill=(6, 8, 22))
        return img

    def _build_reel_talk_backdrop(self) -> Image.Image:
        """
        Builds a warm talk-show / interview studio frame reminiscent of the
        'REEL TALK / DAVID SPADE' video clip in the upper-right of the reference image.
        """
        W = self.width - self.split_x
        H = self.upper_h
        img = Image.new("RGB", (W, H), color=(48, 54, 64))
        draw = ImageDraw.Draw(img)

        # Soft out-of-focus studio background gradient
        for y in range(H):
            t = y / float(max(1, H))
            r = int(68 - t * 28)
            g = int(74 - t * 30)
            b = int(82 - t * 32)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # Bright studio window / monitor glow in upper-left of the video frame
        draw.rectangle([self._s(18), self._s(6), self._s(265), self._s(165)], fill=(212, 224, 238))
        draw.rectangle([self._s(55), self._s(28), self._s(230), self._s(130)], fill=(155, 168, 184))

        # Dark studio equipment / camera boom silhouette on left-mid
        draw.ellipse([self._s(20), self._s(115), self._s(245), self._s(265)], fill=(42, 46, 52))

        # Warm studio key-light halo on right
        draw.ellipse([self._s(250), -self._s(20), self._s(580), self._s(220)], fill=(118, 112, 108))

        # Subject silhouette (slate-blue collared shirt & jacket + warm skin tone portrait)
        cx = self._s(375)
        # Shoulders / Slate-blue collared jacket (matching reference photo)
        draw.polygon(
            [
                (cx - self._s(195), H),
                (cx - self._s(165), self._s(205)),
                (cx - self._s(65), self._s(168)),
                (cx + self._s(75), self._s(168)),
                (cx + self._s(190), self._s(215)),
                (cx + self._s(235), H),
            ],
            fill=(96, 104, 124),
        )
        # Inner dark crew shirt
        draw.polygon(
            [
                (cx - self._s(36), self._s(185)),
                (cx + self._s(42), self._s(185)),
                (cx + self._s(28), H),
                (cx - self._s(24), H),
            ],
            fill=(54, 58, 72),
        )
        # Shirt collar lapels
        draw.polygon(
            [
                (cx - self._s(65), self._s(168)),
                (cx - self._s(22), self._s(172)),
                (cx - self._s(42), self._s(232)),
                (cx - self._s(82), self._s(204)),
            ],
            fill=(116, 124, 145),
        )
        draw.polygon(
            [
                (cx + self._s(70), self._s(168)),
                (cx + self._s(28), self._s(172)),
                (cx + self._s(52), self._s(232)),
                (cx + self._s(88), self._s(204)),
            ],
            fill=(116, 124, 145),
        )
        # Neck & Head (softly blurred like 90s composite video)
        draw.rectangle([cx - self._s(34), self._s(122), cx + self._s(38), self._s(192)], fill=(208, 188, 174))
        draw.ellipse([cx - self._s(72), self._s(10), cx + self._s(78), self._s(162)], fill=(216, 196, 180))
        # Sandy blonde 90s layered hair
        draw.chord([cx - self._s(82), -self._s(12), cx + self._s(88), self._s(110)], start=165, end=15, fill=(168, 142, 108))
        draw.ellipse([cx - self._s(82), self._s(12), cx - self._s(48), self._s(118)], fill=(156, 130, 98))
        draw.ellipse([cx + self._s(52), self._s(16), cx + self._s(86), self._s(124)], fill=(148, 122, 92))
        # Subtle facial features (softly blurred below)
        draw.ellipse([cx - self._s(38), self._s(56), cx - self._s(14), self._s(70)], fill=(142, 124, 114))
        draw.ellipse([cx + self._s(14), self._s(58), cx + self._s(38), self._s(72)], fill=(142, 124, 114))
        draw.rectangle([cx - self._s(18), self._s(114), cx + self._s(18), self._s(124)], fill=(168, 134, 126))

        # Apply authentic composite VHS/cable video softness to the quarter-screen feed
        img = img.filter(ImageFilter.GaussianBlur(self._s(4)))
        return img

    def _build_cinema_backdrop(self) -> Image.Image:
        W = self.width - self.split_x
        H = self.upper_h
        img = Image.new("RGB", (W, H), color=(28, 12, 38))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            t = y / float(max(1, H))
            draw.line([(0, y), (W, y)], fill=(int(58 - t * 34), int(18 - t * 10), int(72 - t * 42)))
        # Spotlight beams
        draw.polygon([(0, H), (self._s(180), 0), (self._s(310), 0), (self._s(90), H)], fill=(86, 54, 108))
        draw.polygon([(W, H), (self._s(420), 0), (self._s(540), 0), (W - self._s(60), H)], fill=(78, 48, 98))
        img = img.filter(ImageFilter.GaussianBlur(self._s(6)))
        return img

    def _build_studio_backdrop(self) -> Image.Image:
        W = self.width - self.split_x
        H = self.upper_h
        img = Image.new("RGB", (W, H), color=(16, 34, 68))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            t = y / float(max(1, H))
            draw.line([(0, y), (W, y)], fill=(int(24 + t * 20), int(48 - t * 18), int(96 - t * 40)))
        draw.ellipse([self._s(140), self._s(20), W - self._s(80), H - self._s(20)], outline=(72, 116, 184), width=4)
        img = img.filter(ImageFilter.GaussianBlur(self._s(3)))
        return img

    def _render_topleft_quadrant(self, frame: Image.Image, card: Dict[str, Any]) -> None:
        """
        Renders the Top-Left Prevue Promo / Custom Message Box:
            Cinemax
        "Black Sheep" [PG-13]
           Wednesday
           Channel 14
        """
        frame.paste(self._topleft_bg, (0, 0))
        W = self.split_x

        network = str(card.get("network", "")).strip()
        title = str(card.get("title", "")).strip()
        rating = str(card.get("rating", "")).strip().upper()
        day_time = str(card.get("day_time", "")).strip()
        channel_info = str(card.get("channel_info", "")).strip()

        white_fill = (238, 242, 255)
        yellow_fill = (246, 224, 58)
        shadow = (4, 8, 28)
        sh_off = (self._s(3), self._s(3))

        # Line 1: Network / Header (y = 26)
        if network:
            nw_w = self._measure_condensed(network, self.font_promo_line, stretch_x=0.86)
            self._draw_condensed_text(
                frame,
                ((W - nw_w) // 2, self._s(26)),
                network,
                self.font_promo_line,
                fill=white_fill,
                shadow_fill=shadow,
                shadow_offset=sh_off,
                stretch_x=0.86,
            )

        # Line 2: Featured Title (yellow) + inline yellow-bordered Rating Badge (y = 104)
        if title:
            title_w = self._measure_condensed(title, self.font_promo_line, stretch_x=0.86)
            badge_w = (self._measure_condensed(rating, self.font_badge, stretch_x=0.84) + self._s(22)) if rating else 0
            total_w = title_w + (self._s(12) + badge_w if rating else 0)

            if total_w <= W - self._s(36):
                start_x = (W - total_w) // 2
                self._draw_condensed_text(
                    frame,
                    (start_x, self._s(104)),
                    title,
                    self.font_promo_line,
                    fill=yellow_fill,
                    shadow_fill=shadow,
                    shadow_offset=sh_off,
                    stretch_x=0.86,
                )
                if rating:
                    self._draw_rating_badge(
                        frame,
                        (start_x + title_w + self._s(12), self._s(112)),
                        rating,
                        color=yellow_fill,
                        bg_fill=(24, 32, 68),
                    )
            else:
                # Wrap long title (e.g. RSS headline or long custom bulletin) into 2 lines
                words = title.split()
                half = max(1, len(words) // 2)
                l1 = " ".join(words[:half])
                l2 = " ".join(words[half:])
                w1 = self._measure_condensed(l1, self.font_promo_line, stretch_x=0.84)
                w2 = self._measure_condensed(l2, self.font_promo_line, stretch_x=0.84)
                self._draw_condensed_text(
                    frame,
                    ((W - w1) // 2, self._s(88)),
                    l1,
                    self.font_promo_line,
                    fill=yellow_fill,
                    shadow_fill=shadow,
                    shadow_offset=sh_off,
                    stretch_x=0.84,
                )
                self._draw_condensed_text(
                    frame,
                    ((W - w2) // 2, self._s(132)),
                    l2,
                    self.font_promo_line,
                    fill=yellow_fill,
                    shadow_fill=shadow,
                    shadow_offset=sh_off,
                    stretch_x=0.84,
                )

        # Line 3: Day / Time (y = 186)
        if day_time:
            dt_w = self._measure_condensed(day_time, self.font_promo_line, stretch_x=0.86)
            self._draw_condensed_text(
                frame,
                ((W - dt_w) // 2, self._s(186)),
                day_time,
                self.font_promo_line,
                fill=white_fill,
                shadow_fill=shadow,
                shadow_offset=sh_off,
                stretch_x=0.86,
            )

        # Line 4: Channel Info (y = 262)
        if channel_info:
            ch_w = self._measure_condensed(channel_info, self.font_promo_line, stretch_x=0.86)
            self._draw_condensed_text(
                frame,
                ((W - ch_w) // 2, self._s(262)),
                channel_info,
                self.font_promo_line,
                fill=white_fill,
                shadow_fill=shadow,
                shadow_offset=sh_off,
                stretch_x=0.86,
            )

    def _render_topright_quadrant(self, frame: Image.Image, slide: Dict[str, Any]) -> None:
        """
        Renders the Top-Right Quarter-Screen Feature Window with the iconic
        Prevue lower-third gold/white title overlay ('REEL TALK / DAVID SPADE').
        """
        rw = self.width - self.split_x
        rh = self.upper_h
        img_url = str(slide.get("image_url", "")).strip()
        theme = str(slide.get("theme", "reel_talk")).strip()

        cached_im = epg_manager.get_cached_slide_image(img_url) if img_url else None
        if cached_im is not None:
            bg = cached_im.resize((rw, rh), Image.BILINEAR)
        else:
            bg = self._right_backdrops.get(theme, self._right_backdrops["reel_talk"]).copy()

        frame.paste(bg, (self.split_x, 0))

        # Lower-Third Prevue Overlay ('REEL TALK' in warm amber-gold + 'DAVID SPADE' in white caps)
        title = str(slide.get("title", "")).strip().upper()
        subtitle = str(slide.get("subtitle", "")).strip().upper()

        lx = self.split_x + self._s(6)
        if title:
            # Warm dark-amber glow band behind the lower-third text
            glow_w = self._measure_condensed(title, self.font_lt_gold, stretch_x=0.96) + self._s(24)
            glow = Image.new("RGB", (min(rw, glow_w), self._s(88)), color=(62, 42, 14))
            glow_mask = Image.new("L", (min(rw, glow_w), self._s(88)), color=140)
            glow_mask = glow_mask.filter(ImageFilter.GaussianBlur(self._s(10)))
            frame.paste(glow, (lx, self._s(236)), glow_mask)

            self._draw_condensed_text(
                frame,
                (lx, self._s(236)),
                title,
                self.font_lt_gold,
                fill=(246, 196, 58),
                shadow_fill=(24, 14, 4),
                shadow_offset=(self._s(4), self._s(4)),
                stretch_x=0.96,
            )

        if subtitle:
            self._draw_condensed_text(
                frame,
                (lx + self._s(4), self._s(288)),
                subtitle,
                self.font_lt_sub,
                fill=(232, 236, 244),
                shadow_fill=(14, 14, 18),
                shadow_offset=(self._s(3), self._s(3)),
                stretch_x=0.82,
            )

    def _draw_beveled_cell(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        palette: Dict[str, ColorRGB],
        bevel_px: int = 3,
    ) -> None:
        """
        Draws a 3D beveled Prevue Guide cell with vertical gradient face,
        bright top/left bevel, dark bottom/right bevel, and crisp dark outer border.
        """
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            return
        draw.rectangle([x0, y0, x1, y1], fill=palette["border"])
        ix0, iy0, ix1, iy1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
        if ix1 <= ix0 or iy1 <= iy0:
            return

        # Vertical gradient face
        ft = palette["face_top"]
        fb = palette["face_bot"]
        span = max(1, iy1 - iy0)
        for y in range(iy0, iy1 + 1):
            t = (y - iy0) / float(span)
            c = (
                int(ft[0] + (fb[0] - ft[0]) * t),
                int(ft[1] + (fb[1] - ft[1]) * t),
                int(ft[2] + (fb[2] - ft[2]) * t),
            )
            draw.line([(ix0, y), (ix1, y)], fill=c)

        # Top & Left light bevel
        bl = palette["bevel_light"]
        bd = palette["bevel_dark"]
        for b in range(bevel_px):
            draw.line([(ix0 + b, iy0 + b), (ix1 - b, iy0 + b)], fill=bl)
            draw.line([(ix0 + b, iy0 + b), (ix0 + b, iy1 - b)], fill=bl)
            draw.line([(ix0 + b, iy1 - b), (ix1 - b, iy1 - b)], fill=bd)
            draw.line([(ix1 - b, iy0 + b), (ix1 - b, iy1 - b)], fill=bd)

    def _render_timebar(self, frame: Image.Image, now_dt: datetime, use_12h: bool) -> None:
        """
        Renders the Middle 3D Beveled Time Bar:
        | 10:45:11 |   10:30 AM   |   11:00 AM   |   11:30 AM  _ |
        """
        draw = ImageDraw.Draw(frame)
        y0 = self.timebar_y
        y1 = y0 + self.timebar_h - 1

        timebar_palette = {
            "face_top": (68, 92, 152),
            "face_bot": (46, 66, 118),
            "bevel_light": (132, 158, 218),
            "bevel_dark": (20, 30, 68),
            "border": (6, 10, 24),
        }

        # 1. Clock Cell (0 .. chan_col_w)
        self._draw_beveled_cell(draw, (0, y0, self.chan_col_w - 1, y1), timebar_palette, bevel_px=self._s(3))

        if use_12h:
            hr = now_dt.hour % 12 or 12
            clock_str = f"{hr}:{now_dt.strftime('%M:%S')}"
        else:
            clock_str = now_dt.strftime("%H:%M:%S")

        cw = self._measure_condensed(clock_str, self.font_clock, stretch_x=0.84)
        self._draw_condensed_text(
            frame,
            ((self.chan_col_w - cw) // 2, y0 + self._s(13)),
            clock_str,
            self.font_clock,
            fill=(240, 244, 255),
            shadow_fill=(6, 8, 20),
            shadow_offset=(self._s(3), self._s(3)),
            stretch_x=0.84,
        )

        # 2. Three 30-Minute Time-Slot Headers
        floored_min = 30 if now_dt.minute >= 30 else 0
        slot0_dt = now_dt.replace(minute=floored_min, second=0, microsecond=0)

        for i in range(3):
            sx0 = self.chan_col_w + i * self.slot_w
            sx1 = self.width - 1 if i == 2 else (sx0 + self.slot_w - 1)
            self._draw_beveled_cell(draw, (sx0, y0, sx1, y1), timebar_palette, bevel_px=self._s(3))

            slot_dt = slot0_dt + timedelta(minutes=30 * i)
            if use_12h:
                shr = slot_dt.hour % 12 or 12
                ampm = "AM" if slot_dt.hour < 12 else "PM"
                slot_str = f"{shr}:{slot_dt.strftime('%M')} {ampm}"
            else:
                slot_str = slot_dt.strftime("%H:%M")

            sw = self._measure_condensed(slot_str, self.font_timeslot, stretch_x=0.86)
            cell_w = sx1 - sx0
            self._draw_condensed_text(
                frame,
                (sx0 + (cell_w - sw) // 2, y0 + self._s(12)),
                slot_str,
                self.font_timeslot,
                fill=(248, 226, 62),
                shadow_fill=(8, 10, 24),
                shadow_offset=(self._s(3), self._s(3)),
                stretch_x=0.86,
            )

            # Iconic Prevue status dash at the bottom-right of the 3rd time slot
            if i == 2:
                dash_x = sx1 - self._s(110)
                dash_y = y1 - self._s(12)
                draw.rectangle(
                    [dash_x, dash_y, dash_x + self._s(20), dash_y + self._s(4)],
                    fill=(235, 240, 255),
                )

    def _draw_continuation_chevron(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y_top: int,
        y_bot: int,
        direction: str = "left",
    ) -> None:
        """
        Draws the tall white Prevue continuation chevron ('<' or '>>') inside a program cell
        when a program started before the window ('left') or continues after ('right').
        """
        ymid = (y_top + y_bot) // 2
        w = self._s(14)
        thick = self._s(6)
        sh = self._s(3)

        if direction == "left":
            # Pointing left (<)
            pts = [
                (x + w, y_top),
                (x + w + thick, y_top),
                (x + thick, ymid),
                (x + w + thick, y_bot),
                (x + w, y_bot),
                (x, ymid),
            ]
        else:
            # Pointing right (>) with double-chevron stripe like reference image
            pts = [
                (x, y_top),
                (x + thick, y_top),
                (x + w + thick, ymid),
                (x + thick, y_bot),
                (x, y_bot),
                (x + w, ymid),
            ]

        shadow_pts = [(px + sh, py + sh) for px, py in pts]
        draw.polygon(shadow_pts, fill=(8, 12, 26))
        draw.polygon(pts, fill=(242, 246, 255))

        if direction == "right":
            off = self._s(10)
            pts2 = [(px + off, py) for px, py in pts]
            shadow_pts2 = [(px + sh, py + sh) for px, py in pts2]
            draw.polygon(shadow_pts2, fill=(8, 12, 26))
            draw.polygon(pts2, fill=(242, 246, 255))

    def _render_program_lines(
        self,
        canvas: Image.Image,
        box: Tuple[int, int, int, int],
        prog: ProgramBlock,
        started_before: bool,
        continues_after: bool,
    ) -> None:
        """
        Renders the 2-line program text and inline boxed Rating Badge ([PG-13], [PG], [R])
        inside a 3D beveled program bar, matching the exact look of:
          "Jackie Chan's First          | "Star Trek:    >>
          Strike" [PG-13] (1996)        | First          >>
        """
        x0, y0, x1, y1 = box
        left_pad = self._s(28) if started_before else self._s(14)
        right_pad = self._s(34) if continues_after else self._s(12)
        avail_w = (x1 - x0) - left_pad - right_pad
        if avail_w < self._s(40):
            return

        # Build tokens where ("BADGE", rating) represents the inline boxed rating badge
        tokens: List[Tuple[str, str]] = []
        for w in prog.title.split():
            tokens.append(("WORD", w))
        if prog.rating:
            tokens.append(("BADGE", prog.rating))
        if prog.year:
            tokens.append(("WORD", f"({prog.year})"))
        if prog.desc:
            for w in prog.desc.split():
                tokens.append(("WORD", w))

        # Greedily pack tokens into up to 2 lines within avail_w
        lines: List[List[Tuple[str, str]]] = [[], []]
        line_idx = 0
        cur_w = 0
        space_w = self._s(9)

        for ttype, tval in tokens:
            if ttype == "BADGE":
                tw = self._measure_condensed(tval, self.font_badge, stretch_x=0.84) + self._s(16)
            else:
                tw = self._measure_condensed(tval, self.font_prog, stretch_x=0.85)

            needed = tw if cur_w == 0 else (space_w + tw)
            if cur_w + needed <= avail_w or cur_w == 0:
                lines[line_idx].append((ttype, tval))
                cur_w += needed
            else:
                line_idx += 1
                if line_idx >= 2:
                    break
                lines[line_idx].append((ttype, tval))
                cur_w = tw

        # Draw each line
        y_positions = [y0 + self._s(8), y0 + self._s(46)]
        for idx, line_tokens in enumerate(lines):
            if not line_tokens:
                continue
            cx = x0 + left_pad
            cy = y_positions[idx]
            for ttype, tval in line_tokens:
                if ttype == "BADGE":
                    bw = self._draw_rating_badge(
                        canvas,
                        (cx, cy + self._s(5)),
                        tval,
                        color=(240, 244, 255),
                        bg_fill=None,
                    )
                    cx += bw + space_w
                else:
                    ww = self._draw_condensed_text(
                        canvas,
                        (cx, cy),
                        tval,
                        self.font_prog,
                        fill=(242, 246, 255),
                        shadow_fill=(8, 10, 22),
                        shadow_offset=(self._s(3), self._s(3)),
                        stretch_x=0.85,
                    )
                    cx += ww + space_w

    def _render_single_grid_row(self, row: GuideRow) -> Image.Image:
        """Renders a single 92px-tall row of the rolling TV guide grid."""
        row_img = Image.new("RGB", (self.width, self.row_h), color=(14, 22, 68))
        draw = ImageDraw.Draw(row_img)

        # Left Channel Cell (x: 0 .. chan_col_w)
        draw.rectangle([0, 0, self.chan_col_w - 1, self.row_h - 1], fill=(16, 24, 72))
        draw.line([(0, 0), (self.chan_col_w - 1, 0)], fill=(54, 74, 134), width=2)
        draw.line([(0, self.row_h - 2), (self.chan_col_w - 1, self.row_h - 2)], fill=(6, 10, 28), width=2)
        draw.line([(self.chan_col_w - 2, 0), (self.chan_col_w - 2, self.row_h - 1)], fill=(6, 10, 28), width=2)

        yellow = (246, 224, 58)
        shadow = (6, 8, 22)

        if row.row_type == "message":
            # Full-width In-Grid Custom Message Banner
            cs_w = self._measure_condensed(row.callsign, self.font_chan, stretch_x=0.84)
            self._draw_condensed_text(
                row_img,
                ((self.chan_col_w - cs_w) // 2, self._s(26)),
                row.callsign,
                self.font_chan,
                fill=yellow,
                shadow_fill=shadow,
                shadow_offset=(self._s(3), self._s(3)),
                stretch_x=0.84,
            )
            palette = BAR_PALETTES.get(row.color_style, BAR_PALETTES["sky_blue"])
            self._draw_beveled_cell(
                draw,
                (self.chan_col_w, 0, self.width - 1, self.row_h - 1),
                palette,
                bevel_px=self._s(3),
            )
            msg_prog = ProgramBlock(title=row.message_text, offset_min=0, duration_min=90)
            self._render_program_lines(
                row_img,
                (self.chan_col_w, 0, self.width - 1, self.row_h - 1),
                msg_prog,
                started_before=False,
                continues_after=False,
            )
            return row_img

        # Channel Number (Line 1) & Callsign (Line 2) in yellow
        if row.channel_number:
            nw = self._measure_condensed(row.channel_number, self.font_chan, stretch_x=0.85)
            self._draw_condensed_text(
                row_img,
                ((self.chan_col_w - nw) // 2, self._s(8)),
                row.channel_number,
                self.font_chan,
                fill=yellow,
                shadow_fill=shadow,
                shadow_offset=(self._s(3), self._s(3)),
                stretch_x=0.85,
            )
        if row.callsign:
            cw = self._measure_condensed(row.callsign, self.font_chan, stretch_x=0.85)
            self._draw_condensed_text(
                row_img,
                ((self.chan_col_w - cw) // 2, self._s(46)),
                row.callsign,
                self.font_chan,
                fill=yellow,
                shadow_fill=shadow,
                shadow_offset=(self._s(3), self._s(3)),
                stretch_x=0.85,
            )

        # Program cells across the 90-minute window (x: chan_col_w .. width)
        palette = BAR_PALETTES.get(row.color_style, BAR_PALETTES["navy"])
        px_per_min = self.prog_area_w / 90.0

        for prog in row.programs:
            p_start = prog.offset_min
            p_end = prog.offset_min + prog.duration_min
            if p_end <= 0 or p_start >= 90:
                continue

            vis_start = max(0, p_start)
            vis_end = min(90, p_end)
            started_before = p_start < 0
            continues_after = p_end > 90

            x0 = self.chan_col_w + int(round(vis_start * px_per_min))
            x1 = (self.width - 1) if vis_end >= 90 else (self.chan_col_w + int(round(vis_end * px_per_min)) - 1)
            if x1 <= x0 + self._s(8):
                continue

            self._draw_beveled_cell(draw, (x0, 0, x1, self.row_h - 1), palette, bevel_px=self._s(3))

            if started_before:
                self._draw_continuation_chevron(
                    draw,
                    x0 + self._s(8),
                    self._s(10),
                    self.row_h - self._s(10),
                    direction="left",
                )
            if continues_after:
                self._draw_continuation_chevron(
                    draw,
                    x1 - self._s(30),
                    self._s(10),
                    self.row_h - self._s(10),
                    direction="right",
                )

            self._render_program_lines(
                row_img,
                (x0, 0, x1, self.row_h - 1),
                prog,
                started_before=started_before,
                continues_after=continues_after,
            )

        return row_img

    def _build_mask(self, scanlines: bool, vignette: bool) -> Image.Image:
        W, H = self.width, self.height
        mask_l = Image.new("L", (W, H), color=255)
        pixels = mask_l.load()
        cx, cy = W / 2.0, H / 2.0

        for y in range(H):
            scan_factor = 0.89 if (scanlines and (y % 2 == 1)) else 1.0
            dy = (y - cy) / cy
            for x in range(W):
                if vignette:
                    dx = (x - cx) / cx
                    r2 = (dx * dx * 0.42) + (dy * dy * 0.42)
                    vig = max(0.72, 1.0 - (r2 * r2 * 0.42))
                else:
                    vig = 1.0
                pixels[x, y] = max(0, min(255, int(255 * scan_factor * vig)))
        return Image.merge("RGB", (mask_l, mask_l, mask_l))

    def _build_noise_frames(self, count: int = 8) -> List[Image.Image]:
        W, H = self.width, self.height
        nw, nh = max(1, W // 2), max(1, H // 2)
        frames: List[Image.Image] = []
        rng = random.Random(1996)
        for _ in range(count):
            buf = bytearray(nw * nh)
            for i in range(nw * nh):
                r = rng.randint(0, 100)
                if r > 97:
                    buf[i] = rng.randint(7, 14)
                elif r > 85:
                    buf[i] = rng.randint(2, 5)
                else:
                    buf[i] = 0
            small_l = Image.frombytes("L", (nw, nh), bytes(buf)).resize((W, H), Image.NEAREST)
            rgb_noise = Image.merge("RGB", (small_l, small_l, small_l))
            frames.append(rgb_noise)
        return frames

    def render_frame(self, now_mono: Optional[float] = None) -> Image.Image:
        """Render a single 24-bit RGB video frame of the Rolling Prevue Guide."""
        if now_mono is None:
            now_mono = time.monotonic()
        elapsed = max(0.0, now_mono - self._start_time)

        disp = settings_store.get_display()
        frame = Image.new("RGB", (self.width, self.height), color=(10, 16, 48))

        promo_dur = max(3.0, float(disp.get("promo_duration", config.PROMO_DURATION)))
        promo_step = int(elapsed // promo_dur)

        # 1. Upper-Left Quadrant: Customizable Prevue Promo / Bulletin Card
        tl_cards = epg_manager.get_topleft_cards()
        active_card = tl_cards[promo_step % len(tl_cards)]
        self._render_topleft_quadrant(frame, active_card)

        # 2. Upper-Right Quadrant: Feature Window with Lower-Third Overlay
        tr_slides = epg_manager.get_topright_slides()
        active_slide = tr_slides[promo_step % len(tr_slides)]
        self._render_topright_quadrant(frame, active_slide)

        # 3. Middle Time Bar (Clock + Three 30-Minute Time-Slot Columns)
        now_dt = datetime.now()
        use_12h = bool(disp.get("time_format_12h", True))
        self._render_timebar(frame, now_dt, use_12h)

        # 4. Bottom Half: Smooth Vertical Rolling TV Guide Grid
        rows = epg_manager.get_rolling_rows()
        num_rows = len(rows)
        scroll_speed = max(0.0, float(disp.get("scroll_speed", config.SCROLL_SPEED))) * self.scale
        total_cycle_px = max(1, num_rows * self.row_h)
        scroll_px = int(elapsed * scroll_speed) % total_cycle_px

        first_row_idx = scroll_px // self.row_h
        first_row_y_offset = -(scroll_px % self.row_h)

        grid_viewport = Image.new("RGB", (self.width, self.grid_h), color=(12, 18, 56))
        cy = first_row_y_offset
        r_offset = 0
        while cy < self.grid_h:
            row_obj = rows[(first_row_idx + r_offset) % num_rows]
            row_img = self._render_single_grid_row(row_obj)
            grid_viewport.paste(row_img, (0, cy))
            cy += self.row_h
            r_offset += 1

        frame.paste(grid_viewport, (0, self.grid_y))

        # 5. CRT Scanlines, Vignette & Analog Noise
        use_scan = bool(disp.get("scanlines", config.SCANLINES))
        use_vig = bool(disp.get("crt_vignette", config.CRT_VIGNETTE))
        use_noise = bool(disp.get("crt_noise", config.CRT_NOISE))

        if use_scan and use_vig:
            frame = ImageChops.multiply(frame, self._scanline_mask)
        elif use_scan:
            frame = ImageChops.multiply(frame, self._scanline_only_mask)
        elif use_vig:
            frame = ImageChops.multiply(frame, self._vignette_only_mask)

        if use_noise and self._noise_frames:
            noise = self._noise_frames[self._noise_idx % len(self._noise_frames)]
            self._noise_idx += 1
            frame = ImageChops.add(frame, noise)

        return frame

    def render_png_bytes(self) -> bytes:
        img = self.render_frame()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


renderer = PrevueGuideRenderer()
