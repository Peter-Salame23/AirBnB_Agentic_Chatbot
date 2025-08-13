import pandas as pd
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, date

AMENITY_SYNONYMS = {
    "wifi": [r"\bwifi\b", r"\bwi-?fi\b", r"wireless internet"],
    "gym": [r"\bgym\b", r"fitness center", r"fitness room"],
    "pool": [r"\bpool\b", r"swimming pool"],
    "hot tub": [r"hot tub", r"jacuzzi"],
    "parking": [r"parking", r"free parking"],
}

def _normalize_amenity_patterns(amenities: List[str]):
    pats = []
    for a in amenities:
        key = str(a).strip().lower()
        variants = AMENITY_SYNONYMS.get(key, [re.escape(key)])
        for v in variants:
            pats.append(re.compile(v, flags=re.IGNORECASE))
    return pats

def _parse_price(value) -> Optional[float]:
    if value is None:
        return None
    s = str(value)
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", s.replace(",", ""))
    return float(m.group(1)) if m else None

def _parse_iso(d: str) -> date:
    y, m, d = map(int, d.split("-"))
    return date(y, m, d)

class Recommender:
    def __init__(self, csv_path: str = "listings.csv", reservations_path: str = "reservations.csv"):
        self.csv_path = csv_path
        self.reservations_path = reservations_path
        self.df = pd.read_csv(csv_path)
        # Normalize some columns
        for col in ["amenities", "location", "property_type", "availability", "name"]:
            if col in self.df.columns:
                self.df[col] = self.df[col].astype(str)

    def recommend(self, criteria: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        df = self.df.copy()

        # 1) Availability
        if "availability" in df.columns:
            df = df[df["availability"].str.contains("Available", case=False, na=False)]

        # 2) Location (contains)
        loc = (criteria.get("location") or "").strip()
        if loc and "location" in df.columns:
            df = df[df["location"].str.contains(loc, case=False, na=False)]
        if df.empty:
            return []

        # 3) Property type (soft filter)
        pt_req = (criteria.get("property_type") or "").strip().lower()
        df_pt = df
        if pt_req and "property_type" in df.columns:
            tmp = df[df["property_type"].str.lower().str.contains(pt_req, na=False)]
            if not tmp.empty:
                df_pt = tmp

        # 4) Amenity scoring
        requested_amenities = criteria.get("amenities") or []
        if isinstance(requested_amenities, str):
            requested_amenities = [x.strip() for x in requested_amenities.split(",") if x.strip()]
        amen_patterns = _normalize_amenity_patterns(requested_amenities)

        def amenity_score(s: str) -> int:
            if not amen_patterns:
                return 0
            t = s or ""
            return sum(1 for p in amen_patterns if p.search(t))

        if "amenities" in df_pt.columns:
            df_pt = df_pt.copy()
            df_pt["amenity_matches"] = df_pt["amenities"].apply(amenity_score)
        else:
            df_pt = df_pt.copy()
            df_pt["amenity_matches"] = 0

        # 5) Guests → soft capacity via bedrooms (if column exists)
        guests = criteria.get("number_of_guests")
        if guests and "bedrooms" in df_pt.columns:
            try:
                import math
                needed = max(1, math.ceil(int(guests) / 2))
                df_pt = df_pt[df_pt["bedrooms"].fillna(0).astype(int) >= needed]
            except Exception:
                pass

        if df_pt.empty:
            return []

        # 6) Sort for best options
        sort_cols, asc = ["amenity_matches"], [False]
        if "rating" in df_pt.columns:
            sort_cols.append("rating"); asc.append(False)
        if "reviews_count" in df_pt.columns:
            sort_cols.append("reviews_count"); asc.append(False)
        df_pt = df_pt.sort_values(by=sort_cols, ascending=asc)

        # 7) Output fields
        output_cols_priority = [
            "listing_id","name","location","price_per_night",
            "bedrooms","rating","reviews_count","amenities","property_type","availability"
        ]
        cols_present = [c for c in output_cols_priority if c in df_pt.columns]
        return df_pt.head(top_k)[cols_present].to_dict("records")

    def reserve(
        self,
        listing_id: int,
        criteria: Dict[str, Any],
        customer: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reserve a listing (simple model: one-at-a-time availability).
        - listing_id: int
        - criteria: includes date_checkin, date_checkout, number_of_guests
        - customer: optional {"name": "...", "email": "..."} (we can omit; account username is primary)
        - username: account making the reservation (for per-user filtering)
        Returns a reservation summary dict. Raises ValueError on errors.
        """
        customer = customer or {}

        # 1) find listing
        rows = self.df[self.df["listing_id"] == int(listing_id)]
        if rows.empty:
            raise ValueError("Listing not found.")
        row = rows.iloc[0]

        # 2) check availability
        if str(row.get("availability", "")).lower() != "available":
            raise ValueError("Sorry, this listing is no longer available.")

        # 3) compute price estimate
        checkin = _parse_iso(criteria["date_checkin"])
        checkout = _parse_iso(criteria["date_checkout"])
        if checkout <= checkin:
            raise ValueError("Checkout date must be after check-in date.")
        nights = (checkout - checkin).days

        price_per_night = _parse_price(row.get("price_per_night"))
        estimated_total = round((price_per_night or 0.0) * nights, 2)

        # 4) create reservation record
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        reservation_id = f"R-{listing_id}-{ts}"

        reservation = {
            "reservation_id": reservation_id,
            "listing_id": int(row["listing_id"]),
            "name": row.get("name"),
            "location": row.get("location"),
            "property_type": row.get("property_type"),
            "price_per_night": row.get("price_per_night"),
            "rating": row.get("rating"),
            "reviews_count": row.get("reviews_count"),
            "amenities": row.get("amenities"),
            # Guest info is optional now; account username is the key identifier
            "guest_name": customer.get("name"),
            "guest_email": customer.get("email"),
            "date_checkin": criteria["date_checkin"],
            "date_checkout": criteria["date_checkout"],
            "number_of_guests": criteria.get("number_of_guests"),
            "nights": nights,
            "estimated_total": estimated_total,
            "status": "Booked",
            "created_utc": ts,
            "username": username,
        }

        # 5) persist: mark listing as Booked and save CSV
        idx = rows.index[0]
        self.df.at[idx, "availability"] = "Booked"
        self.df.to_csv(self.csv_path, index=False)

        # 6) append to reservations.csv (create headers if file empty/missing)
        try:
            try:
                existing = pd.read_csv(self.reservations_path)
            except FileNotFoundError:
                existing = pd.DataFrame()
            except pd.errors.EmptyDataError:
                existing = pd.DataFrame()

            updated = pd.concat([existing, pd.DataFrame([reservation])], ignore_index=True)
            updated.to_csv(self.reservations_path, index=False)
        except Exception:
            # If writing reservations fails, still keep listing as booked; but surface a warning
            reservation["warning"] = "Failed to record reservation to reservations.csv, but listing marked Booked."

        return reservation
