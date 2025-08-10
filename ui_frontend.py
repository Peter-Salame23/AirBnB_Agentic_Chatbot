# ui_frontend.py
import os, json, time, re, hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# ------------------- Appearance -------------------
def inject_css():
    st.markdown(
        """
        <style>
        .prop-card {
            border-radius: 16px;
            padding: 12px;
            background: var(--background, #ffffff);
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
            border: 1px solid rgba(0,0,0,0.10);
        }
        .prop-title { font-weight: 700; margin: 6px 0 2px 0; }
        .prop-subtitle { color: #888; font-size: 0.9rem; margin-bottom: 6px; }
        .prop-meta { font-size: 0.9rem; line-height: 1.35rem; }
        .prop-amenities { font-size: 0.85rem; color: #888; margin-top: 6px; }
        .prop-price { font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ------------------- Type helpers -------------------
TYPE_KEYWORDS: Dict[str, List[str]] = {
    "hotel": ["hotel"],
    "apartment": ["apartment", "flat", "condo"],
    "house": ["house", "home"],
    "tiny house": ["tiny house"],
    "bungalow": ["bungalow"],
    "cabin": ["cabin"],
    "farmhouse": ["farmhouse"],
    "condo": ["condo"],
    "penthouse": ["penthouse"],
    "studio": ["studio"],
    "villa": ["villa"],
    "chalet": ["chalet"],
    "cottage": ["cottage"],
}

SYNONYMS = {
    "home": "house",
    "homes": "house",
    "flat": "apartment",
    "flats": "apartment",
    "suite": "hotel",
    "tinyhome": "tiny house",
}

def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def normalize_type(t: Optional[str]) -> str:
    if not t:
        return "house"
    t = t.strip().lower()
    t = SYNONYMS.get(t, t)
    for key in TYPE_KEYWORDS.keys():
        if key in t:
            return key
    return t

def _seed_hex_for_listing(listing: Dict) -> str:
    raw = str(listing.get("listing_id") or listing.get("name") or listing).encode("utf-8")
    return hashlib.md5(raw).hexdigest()

def _seed_int_for_listing(listing: Dict) -> int:
    return int(_seed_hex_for_listing(listing), 16)

# ------------------- Local images first -------------------
def pick_local_type_image(ptype: str, seed_int: int, base_dir: str = "assets/images") -> Optional[str]:
    """
    Look for images in assets/images/<ptype-slug>/.
    Returns a deterministic selection if found.
    """
    p = Path(base_dir) / slugify(ptype)
    if not p.exists():
        return None
    candidates = sorted([*p.glob("*.jpg"), *p.glob("*.jpeg"), *p.glob("*.png"), *p.glob("*.webp")])
    if not candidates:
        return None
    idx = seed_int % len(candidates)
    return str(candidates[idx])

# ------------------- Offline placeholder generator -------------------
def _ensure_cache_dir() -> Path:
    cache = Path(".cache/property_images")
    cache.mkdir(parents=True, exist_ok=True)
    return cache

def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return "\n".join(lines)

def generate_placeholder_image(listing: Dict, width: int, height: int) -> str:
    """
    Create a nice offline image with the property type + city.
    Cached per-listing so it renders fast on reruns.
    """
    cache = _ensure_cache_dir()
    seed_hex = _seed_hex_for_listing(listing)
    out_path = cache / f"{seed_hex}_{width}x{height}.png"
    if out_path.exists():
        return str(out_path)

    # Colors based on seed (pleasant dark card with accent)
    seed = _seed_int_for_listing(listing)
    bg = (30 + (seed % 40), 34 + ((seed >> 3) % 40), 40 + ((seed >> 6) % 40))  # dark gray variants
    accent = (120 + (seed % 100), 150 + ((seed >> 5) % 80), 255)               # blue-ish accent

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # Simple gradient bar
    for y in range(height):
        ratio = y / height
        r = int(bg[0] * (1 - ratio) + accent[0] * ratio * 0.25)
        g = int(bg[1] * (1 - ratio) + accent[1] * ratio * 0.25)
        b = int(bg[2] * (1 - ratio) + accent[2] * ratio * 0.25)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Text
    ptype = normalize_type(listing.get("property_type", "House")).title()
    loc = str(listing.get("location", "")).split(",")[0]
    title = f"{ptype}"
    subtitle = loc if loc else ""

    # Try to load a nicer font if available; otherwise default
    try:
        custom_font_path = Path("assets/fonts/Inter-SemiBold.ttf")
        font_title = ImageFont.truetype(str(custom_font_path), 46) if custom_font_path.exists() else ImageFont.load_default()
        font_sub = ImageFont.truetype(str(custom_font_path), 28) if custom_font_path.exists() else ImageFont.load_default()
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    margin = 28
    max_text_width = width - 2 * margin

    title_wrapped = _wrap_text(draw, title, font_title, max_text_width)
    sub_wrapped = _wrap_text(draw, subtitle, font_sub, max_text_width)

    # Position near bottom-left
    title_w, title_h = draw.multiline_textbbox((0, 0), title_wrapped, font=font_title)[2:]
    sub_w, sub_h = draw.multiline_textbbox((0, 0), sub_wrapped, font=font_sub)[2:] if sub_wrapped else (0, 0)
    total_h = title_h + (sub_h + 8 if sub_wrapped else 0)

    x = margin
    y = height - total_h - margin

    # Text shadow for readability
    shadow = (0, 0, 0)
    draw.multiline_text((x+2, y+2), title_wrapped, font=font_title, fill=shadow, align="left")
    draw.multiline_text((x, y), title_wrapped, font=font_title, fill=(240, 240, 240), align="left")

    if sub_wrapped:
        y2 = y + title_h + 8
        draw.multiline_text((x+1, y2+1), sub_wrapped, font=font_sub, fill=shadow, align="left")
        draw.multiline_text((x, y2), sub_wrapped, font=font_sub, fill=(220, 220, 220), align="left")

    img.save(out_path, format="PNG", optimize=True)
    return str(out_path)

# ------------------- Unsplash key + status -------------------
_UNSPLASH_STATUS_SHOWN = False

def _get_unsplash_key() -> Optional[str]:
    # Prefer Streamlit secrets (works on Cloud + local .streamlit/secrets.toml)
    key = None
    try:
        key = st.secrets.get("UNSPLASH_ACCESS_KEY") or st.secrets.get("unsplash_access_key")
    except Exception:
        pass
    if not key:
        load_dotenv()
        key = os.getenv("UNSPLASH_ACCESS_KEY")
    return key

def _show_unsplash_status(ok: bool, msg: str):
    global _UNSPLASH_STATUS_SHOWN
    if _UNSPLASH_STATUS_SHOWN:
        return
    _UNSPLASH_STATUS_SHOWN = True
    if ok:
        st.toast("✅ Unsplash connected", icon="✅")
    else:
        st.warning(f"Unsplash not active → {msg}. Using local/placeholder images.")

# ------------------- On-demand Unsplash fetch (cached) -------------------
_UNSPLASH_MAP_PATH = Path(".cache/unsplash_ui_map.json")

def _load_unsplash_cache() -> dict:
    if _UNSPLASH_MAP_PATH.exists():
        try:
            return json.loads(_UNSPLASH_MAP_PATH.read_text())
        except Exception:
            return {}
    return {}

def _save_unsplash_cache(d: dict):
    _UNSPLASH_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UNSPLASH_MAP_PATH.write_text(json.dumps(d, indent=2))

def _unsplash_query_for(listing: Dict) -> str:
    ptype = normalize_type(listing.get("property_type", "house"))
    loc   = str(listing.get("location", "")).strip()
    city  = loc.split(",")[0] if loc else ""
    return f"{ptype} in {city}" if city else ptype

def fetch_unsplash_for(listing: Dict) -> Optional[Tuple[str, str]]:
    """
    Returns (image_url, credit) or None if not found.
    Caches responses so we don't re-hit the API.
    """
    key = _get_unsplash_key()
    if not key:
        _show_unsplash_status(False, "Missing UNSPLASH_ACCESS_KEY (set st.secrets or .env).")
        return None

    _show_unsplash_status(True, "")

    cache = _load_unsplash_cache()
    seed = _seed_hex_for_listing(listing)
    if seed in cache and cache[seed].get("image_url"):
        it = cache[seed]
        return it["image_url"], it.get("image_credit", "")

    q = _unsplash_query_for(listing)

    def _search(query: str) -> Optional[dict]:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape", "content_filter": "high"},
            headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
            timeout=15,
        )
        # Simple backoff on rate limit
        if r.status_code == 429:
            time.sleep(1.5)
            r = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1, "orientation": "landscape", "content_filter": "high"},
                headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
                timeout=15,
            )
        r.raise_for_status()
        data = r.json()
        res = data.get("results", [])
        return res[0] if res else None

    try:
        best = _search(q)
        if not best:
            # fallback try: just city or just property type
            loc = str(listing.get("location", "")).strip()
            city = loc.split(",")[0] if loc else ""
            fallback_q = city or normalize_type(listing.get("property_type", "house"))
            best = _search(fallback_q)

        if not best:
            cache[seed] = {"image_url": "", "image_credit": ""}
            _save_unsplash_cache(cache)
            return None

        url = (best.get("urls") or {}).get("regular", "")
        user = best.get("user") or {}
        credit = f"Photo by {user.get('name','Unknown')} on Unsplash ({(user.get('links') or {}).get('html','https://unsplash.com')})"
        cache[seed] = {"image_url": url, "image_credit": credit}
        _save_unsplash_cache(cache)
        return url, credit

    except Exception as e:
        # One-time notice already shown; just skip
        return None

# ------------------- Image selection (now prefers Unsplash) -------------------
def image_for_listing(listing: Dict, width: int = 640, height: int = 400) -> Tuple[str, Optional[str]]:
    """
    Returns (image_src, credit) with priority:
      1) Provided by data: image_path (local) or image_url (remote)
      2) Fetch from Unsplash now (and cache)
      3) Local asset in assets/images/<property_type>/
      4) Generated placeholder (offline, stable)
    """
    # 1) From data
    image_path = str(listing.get("image_path", "") or "").strip()
    if image_path and Path(image_path).exists():
        return image_path, str(listing.get("image_credit", "") or "").strip() or None

    image_url = str(listing.get("image_url", "") or "").strip()
    if image_url:
        return image_url, str(listing.get("image_credit", "") or "").strip() or None

    # 2) Try Unsplash live (UI-side)
    fetched = fetch_unsplash_for(listing)
    if fetched:
        return fetched  # (url, credit)

    # 3) Local by type
    ptype = normalize_type(listing.get("property_type", "house"))
    seed_int = _seed_int_for_listing(listing)
    local = pick_local_type_image(ptype, seed_int)
    if local:
        return local, None

    # 4) Placeholder
    return generate_placeholder_image(listing, width, height), None

# ------------------- Renderer -------------------
def render_recommendations(recs: List[Dict], columns: int = 3) -> Optional[int]:
    """
    Render property cards in a responsive grid.
    Returns the selected listing_id if user clicks “Book”, else None.
    """
    if not recs:
        st.info("No matches with those filters. Try loosening location/type/amenities.")
        return None

    inject_css()
    st.markdown("**⭐ Top options for you:**")

    cols = st.columns(columns)
    selected_id: Optional[int] = None

    for i, r in enumerate(recs):
        with cols[i % columns]:
            with st.container(border=True):
                st.markdown('<div class="prop-card">', unsafe_allow_html=True)

                # Prefer Unsplash (image_path / image_url or live fetch) then local/placeholder
                img_src, credit = image_for_listing(r, width=640, height=400)
                st.image(img_src, use_container_width=True)
                if credit:
                    st.caption(credit)

                name = r.get("name", "N/A")
                loc = r.get("location", "N/A")
                ptype = r.get("property_type", "N/A")

                st.markdown(f'<div class="prop-title">{name}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="prop-subtitle">{ptype} • {loc}</div>', unsafe_allow_html=True)

                price = r.get("price_per_night", "N/A")
                rating = r.get("rating", "N/A")
                reviews = r.get("reviews_count", "N/A")
                bedrooms = r.get("bedrooms", "N/A")

                st.markdown(
                    f'<div class="prop-meta">'
                    f'<span class="prop-price">Price/night: {price}</span><br/>'
                    f'Rating: {rating} ({reviews} reviews) • Bedrooms: {bedrooms}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                amenities = str(r.get("amenities", "N/A"))
                if len(amenities) > 120:
                    amenities = amenities[:117] + "..."
                st.markdown(f'<div class="prop-amenities">Amenities: {amenities}</div>', unsafe_allow_html=True)

                # listing_id may be string/None; guard conversion
                lid_val = r.get("listing_id")
                try:
                    lid = int(lid_val)
                except (TypeError, ValueError):
                    lid = None

                if lid is not None and st.button(f"Book (ID {lid})", key=f"book_card_{i}_{lid}"):
                    selected_id = lid

                st.markdown("</div>", unsafe_allow_html=True)

    return selected_id
