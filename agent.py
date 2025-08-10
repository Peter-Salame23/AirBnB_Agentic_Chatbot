# agent.py
import os
import json
import re
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from dateutil.parser import parse as du_parse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

REQUIRED_FIELDS = [
    "location",
    "checkin_date",
    "checkout_date",
    "property_type",
    "amenities",
    "number_of_guests",
]

WEEKDAY_MAP = {
    "monday": MO, "mon": MO,
    "tuesday": TU, "tue": TU, "tues": TU,
    "wednesday": WE, "wed": WE,
    "thursday": TH, "thu": TH, "thur": TH, "thurs": TH,
    "friday": FR, "fri": FR,
    "saturday": SA, "sat": SA,
    "sunday": SU, "sun": SU,
}

NUMBER_WORDS = {
    "zero": 0, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12
}

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _to_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def _word_to_int(token: str) -> Optional[int]:
    token = token.lower().strip()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)

def _resolve_relative_date(text: str, now: datetime) -> Optional[str]:
    if not text:
        return None
    s = text.strip().lower()

    if s == "today":
        return _to_iso(now.date())
    if s in {"tomorrow", "tmrw", "tmr"}:
        return _to_iso((now + timedelta(days=1)).date())

    m = re.match(r"(in\s+)?([a-z0-9]+)\s+day(s)?", s)
    if m:
        n = _word_to_int(m.group(2))
        if n is not None:
            return _to_iso((now + timedelta(days=n)).date())

    m = re.match(r"(in\s+)?([a-z0-9]+)\s+week(s)?", s)
    if m:
        n = _word_to_int(m.group(2))
        if n is not None:
            return _to_iso((now + timedelta(weeks=n)).date())

    m = re.match(r"(in\s+)?([a-z0-9]+)\s+month(s)?", s)
    if m:
        n = _word_to_int(m.group(2))
        if n is not None:
            return _to_iso((now + relativedelta(months=+n)).date())

    if re.match(r"(a|an)\s+week\s+from\s+now", s):
        return _to_iso((now + timedelta(weeks=1)).date())
    if re.match(r"(a|an)\s+month\s+from\s+now", s):
        return _to_iso((now + relativedelta(months=+1)).date())

    m = re.match(r"next\s+([a-z]+)", s)
    if m:
        wd = m.group(1)
        if wd in WEEKDAY_MAP:
            d = (now + relativedelta(weekday=WEEKDAY_MAP[wd](+1))).date()
            return _to_iso(d)

    m = re.match(r"(this|on)\s+([a-z]+)", s)
    if m:
        wd = m.group(2)
        if wd in WEEKDAY_MAP:
            target_idx = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"].index(
                next(full for full in ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
                     if full.startswith(wd[:3]))
            )
            delta = (target_idx - now.weekday()) % 7
            d = (now + timedelta(days=delta)).date()
            return _to_iso(d)

    if s in WEEKDAY_MAP:
        d = (now + relativedelta(weekday=WEEKDAY_MAP[s](+1))).date()
        return _to_iso(d)

    if ISO_RE.match(s):
        try:
            y, m, d = map(int, s.split("-"))
            _ = date(y, m, d)
            return s
        except Exception:
            pass

    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        a, b, c = m.groups()
        mm, dd, yy = int(a), int(b), int(c)
        if yy < 100:
            yy += 2000
        try:
            return _to_iso(date(yy, mm, dd))
        except ValueError:
            try:
                return _to_iso(date(yy, dd, mm))
            except ValueError:
                pass

    try:
        dt = du_parse(s, fuzzy=True, dayfirst=False, default=now)
        return _to_iso(dt.date())
    except Exception:
        return None

class BookingAgent:
    def __init__(self, tz: str = "America/Toronto"):
        self.tz = tz
        self.booking_info: Dict[str, Optional[Any]] = {
            "location": None,
            "checkin_date": None,   # ISO YYYY-MM-DD
            "checkout_date": None,  # ISO YYYY-MM-DD
            "property_type": None,
            "amenities": None,      # list[str]
            "number_of_guests": None,
        }

    def _is_complete(self) -> bool:
        return all(self.booking_info.get(k) not in (None, "", []) for k in REQUIRED_FIELDS)

    def _missing_fields(self):
        return [k for k in REQUIRED_FIELDS if not self.booking_info.get(k)]

    def _final_json(self) -> str:
        data = {
            "location": self.booking_info["location"],
            "date_checkin": self.booking_info["checkin_date"],
            "date_checkout": self.booking_info["checkout_date"],
            "property_type": self.booking_info["property_type"],
            "amenities": self.booking_info["amenities"],
            "number_of_guests": self.booking_info["number_of_guests"],
        }
        return json.dumps(data, indent=2)

    def _parse_amenities(self, value) -> Optional[list]:
        if value is None:
            return None
        if isinstance(value, list):
            out = [str(x).strip() for x in value if str(x).strip()]
            return out or None
        if isinstance(value, str):
            out = [x.strip() for x in value.split(",") if x.strip()]
            return out or None
        # ignore unknown types
        return None

    def _ensure_iso_date(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        s = str(value).strip()
        now = datetime.now(ZoneInfo(self.tz))

        if ISO_RE.match(s):
            try:
                y, m, d = map(int, s.split("-"))
                candidate = date(y, m, d)
                if y < now.year - 1:
                    candidate = date(now.year, m, d)
                    if candidate < now.date():
                        candidate = date(now.year + 1, m, d)
                return _to_iso(candidate)
            except Exception:
                pass

        resolved = _resolve_relative_date(s, now)
        return resolved

    def _normalize_and_update(self, updates: Dict[str, Any]) -> None:
        if not updates:
            return

        if "location" in updates and updates["location"]:
            self.booking_info["location"] = str(updates["location"]).strip()

        if "checkin_date" in updates and updates["checkin_date"]:
            iso = self._ensure_iso_date(updates["checkin_date"])
            if iso:
                self.booking_info["checkin_date"] = iso

        if "checkout_date" in updates and updates["checkout_date"]:
            iso = self._ensure_iso_date(updates["checkout_date"])
            if iso:
                self.booking_info["checkout_date"] = iso

        if "property_type" in updates and updates["property_type"]:
            pt = str(updates["property_type"]).lower()
            if "hotel" in pt:
                pt = "hotel"
            self.booking_info["property_type"] = pt

        if "amenities" in updates:
            self.booking_info["amenities"] = self._parse_amenities(updates["amenities"])

        if "number_of_guests" in updates and updates["number_of_guests"] is not None:
            try:
                self.booking_info["number_of_guests"] = int(updates["number_of_guests"])
            except Exception:
                # try word-to-int
                n = _word_to_int(str(updates["number_of_guests"]))
                if n is not None:
                    self.booking_info["number_of_guests"] = n

        # Ensure checkout > checkin
        ci = self.booking_info.get("checkin_date")
        co = self.booking_info.get("checkout_date")
        if ci and co:
            try:
                y1, m1, d1 = map(int, ci.split("-"))
                y2, m2, d2 = map(int, co.split("-"))
                ci_d = date(y1, m1, d1)
                co_d = date(y2, m2, d2)
                if co_d <= ci_d:
                    co_d = ci_d + timedelta(days=1)
                    self.booking_info["checkout_date"] = _to_iso(co_d)
            except Exception:
                pass

    # -------- LOCAL KEEP-ALIVE QUESTION (no API needed) --------
    def _local_next_question(self) -> str:
        missing = self._missing_fields()
        # Ask in small logical chunks
        if "location" in missing:
            return "Where would you like to stay (city or area)?"
        if "checkin_date" in missing and "checkout_date" in missing:
            return "What are your check-in and check-out dates? You can say things like “next Friday to Sunday.”"
        if "checkin_date" in missing:
            return "What’s your check-in date?"
        if "checkout_date" in missing:
            return "What’s your check-out date?"
        if "property_type" in missing:
            return "What type of property do you prefer (e.g., apartment, house, hotel, cabin, studio, penthouse)?"
        if "number_of_guests" in missing:
            return "How many guests will be staying?"
        if "amenities" in missing:
            return "Any must-have amenities (e.g., wifi, parking, pool, kitchen)? You can list a few."
        # Fallback generic
        return "Tell me a bit more so I can finish your booking details."

    def run(self, user_message: str) -> str:
        # If already complete, return final JSON
        if self._is_complete():
            return self._final_json()

        system_prompt = (
            "You are a very friendly and helpful booking agent named Dr. House. "
            "Extract any booking details from the user's last message and call the tool. "
            "For dates, DO NOT convert relative phrases yourself—pass them as the user said "
            "(e.g., 'today', 'next friday', 'in two weeks', 'a month from now'). "
            "If the user mentions BOTH check-in and check-out, pass both."
        )

        tool_schema = [
            {
                "type": "function",
                "function": {
                    "name": "update_booking",
                    "description": "Update any booking fields found in the user's message.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "checkin_date": {"type": "string"},
                            "checkout_date": {"type": "string"},
                            "property_type": {"type": "string"},
                            "amenities": {
                                "oneOf": [
                                    {"type": "array", "items": {"type": "string"}},
                                    {"type": "string"}
                                ]
                            },
                            # accept string or integer to avoid tool call rejection
                            "number_of_guests": {
                                "oneOf": [{"type": "integer"}, {"type": "string"}]
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            }
        ]

        try:
            # 1) Try to extract structured fields from the user's message
            extraction = client.chat.completions.create(
                model="gpt-4o",
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Current state:\n"
                            + json.dumps(self.booking_info, indent=2)
                            + "\n\nUser said:\n"
                            + user_message
                        ),
                    },
                ],
                tools=tool_schema,
                # let the model decide; avoids hard failure when it doesn't want to call the tool
                tool_choice="auto",
            )

            updated_anything = False
            tool_calls = extraction.choices[0].message.tool_calls or []
            for call in tool_calls:
                if getattr(call, "type", "") == "function" and getattr(call, "function", None):
                    if call.function.name == "update_booking":
                        args = {}
                        if call.function.arguments:
                            try:
                                args = json.loads(call.function.arguments)
                            except Exception:
                                args = {}
                        before = self.booking_info.copy()
                        self._normalize_and_update(args)
                        if self.booking_info != before:
                            updated_anything = True

            # 2) If complete, return final JSON
            if self._is_complete():
                return self._final_json()

            # 3) Ask ONE concise follow-up (model) OR fall back locally
            missing = self._missing_fields()

            # If the model didn't update anything, it's often better to continue anyway
            # with a direct, targeted question to keep the chat alive.
            try:
                followup = client.chat.completions.create(
                    model="gpt-4o",
                    temperature=0.4,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Ask ONE short, friendly follow-up to get the next missing detail(s). "
                                "Be specific; don't repeat known info. No preambles."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Known so far:\n"
                                + json.dumps(self.booking_info, indent=2)
                                + "\n\nMissing (in order): "
                                + ", ".join(missing)
                                + "\n\nWrite exactly one concise question."
                            ),
                        },
                    ],
                )
                question = (followup.choices[0].message.content or "").strip()
                return question if question else self._local_next_question()
            except Exception:
                # If the follow-up generation fails, use local fallback
                return self._local_next_question()

        except Exception:
            # Any upstream API error: keep the chat alive with a local question
            return self._local_next_question()
