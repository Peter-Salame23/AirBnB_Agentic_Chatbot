# unsplash_images.py
import os, json, time, pathlib, re
from typing import Optional, Tuple
import requests
import pandas as pd
from dotenv import load_dotenv

CACHE_DIR = pathlib.Path(".cache/property_images")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAP_PATH = CACHE_DIR / "images_map.json"

UNSPLASH_API = "https://api.unsplash.com/search/photos"

def _load_key() -> str:
    load_dotenv()
    key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not key:
        raise RuntimeError("UNSPLASH_ACCESS_KEY not found in environment (.env).")
    return key

def _read_cache() -> dict:
    if MAP_PATH.exists():
        try:
            return json.loads(MAP_PATH.read_text())
        except Exception:
            return {}
    return {}

def _write_cache(d: dict) -> None:
    MAP_PATH.write_text(json.dumps(d, indent=2))

def _find_cols(df: pd.DataFrame) -> Tuple[str, str]:
    cols = {c.lower(): c for c in df.columns}
    prop_candidates = ["property_type", "type", "category", "home_type"]
    loc_candidates = ["city", "location", "area", "region", "neighborhood"]
    prop_col = next((cols[c] for c in cols if c in prop_candidates), None)
    loc_col  = next((cols[c] for c in cols if c in loc_candidates), None)
    if not prop_col:
        raise ValueError(f"Couldn’t find a property-type column (looked for {prop_candidates}).")
    if not loc_col:
        raise ValueError(f"Couldn’t find a city/location column (looked for {loc_candidates}).")
    return prop_col, loc_col

def _mk_query(prop: str, loc: str) -> str:
    prop = re.sub(r"_", " ", (prop or "").strip())
    loc = (loc or "").strip()
    return f"{prop} in {loc}".strip() if loc else prop

def _search_unsplash(query: str, access_key: str) -> Optional[dict]:
    params = {"query": query, "per_page": 1, "orientation": "landscape", "content_filter": "high"}
    headers = {"Accept-Version": "v1", "Authorization": f"Client-ID {access_key}"}
    r = requests.get(UNSPLASH_API, params=params, headers=headers, timeout=20)
    if r.status_code == 429:
        time.sleep(2)
        r = requests.get(UNSPLASH_API, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        return None
    return data["results"][0]

def _credit(result: dict) -> str:
    if not result:
        return ""
    user = result.get("user") or {}
    name = user.get("name", "Unknown")
    link = (user.get("links") or {}).get("html", "https://unsplash.com")
    return f"Photo by {name} on Unsplash ({link})"

def _download(url: str, out_path: pathlib.Path) -> str:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return str(out_path)

def attach_images_to_csv(
    csv_path: str,
    out_csv: Optional[str] = None,
    download: bool = False,
) -> str:
    access_key = _load_key()
    df = pd.read_csv(csv_path)
    prop_col, loc_col = _find_cols(df)

    for col in ["image_url", "image_credit", "image_path"]:
        if col not in df.columns:
            df[col] = ""

    cache = _read_cache()

    for idx, row in df.iterrows():
        if str(row.get("image_url", "")).strip():
            continue

        q = _mk_query(str(row[prop_col]), str(row[loc_col]))
        if q in cache:
            info = cache[q]
        else:
            result = _search_unsplash(q, access_key)
            if not result:
                fallback_q = str(row[loc_col]).strip() or "city skyline"
                result = _search_unsplash(fallback_q, access_key)
            info = {
                "image_url": (result.get("urls") or {}).get("regular", "") if result else "",
                "credit": _credit(result),
            }
            cache[q] = info
            _write_cache(cache)

        img_url = info.get("image_url", "")
        credit  = info.get("credit", "")

        img_path_val = ""
        if download and img_url:
            out_path = CACHE_DIR / f"{idx}.jpg"
            try:
                img_path_val = _download(img_url, out_path)
            except Exception:
                img_path_val = ""

        df.at[idx, "image_url"]    = img_url
        df.at[idx, "image_credit"] = credit
        df.at[idx, "image_path"]   = img_path_val

    out_csv = out_csv or csv_path
    df.to_csv(out_csv, index=False)
    return out_csv

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Attach Unsplash images to a listings CSV.")
    p.add_argument("--csv", default="listings.csv", help="Path to listings CSV.")
    p.add_argument("--out", default=None, help="Output CSV (default: overwrite input).")
    p.add_argument("--download", action="store_true", help="Download images locally.")
    args = p.parse_args()

    out = attach_images_to_csv(args.csv, args.out, args.download)
    print(f"✅ Image columns written: {out}")
