# agent.py
"""
Minimal chat-style preference collector that works inside Streamlit.
No external LLM required. It asks targeted questions until it has
enough info to search, then returns a dict of preferences.
"""

from typing import Dict, Any, List
import streamlit as st

REQUIRED_ORDER = ["location", "number_of_guests"]
OPTIONAL_ORDER = ["property_type", "budget", "amenities"]

def _missing_keys(d: Dict[str, Any]) -> List[str]:
    return [k for k in REQUIRED_ORDER if not d.get(k)]

def _init_chat_state():
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {"role": "assistant", "content": "Hi! Tell me what you’re looking for. Which city, how many guests, and any preferences?"}
        ]
    if "collected_prefs" not in st.session_state:
        st.session_state.collected_prefs = {
            "location": None,
            "number_of_guests": None,
            "property_type": None,
            "budget": None,
            "amenities": [],
        }

def render_chat_and_collect() -> Dict[str, Any] | None:
    _init_chat_state()

    # Render chat history
    for m in st.session_state.chat_messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # User reply
    user_msg = st.chat_input("Type your preferences…")
    if user_msg:
        st.session_state.chat_messages.append({"role": "user", "content": user_msg})
        _ingest(user_msg)

    # Decide next prompt
    prefs = st.session_state.collected_prefs
    missing = _missing_keys(prefs)

    if missing:
        ask = missing[0]
        prompts = {
            "location": "Which city would you like to stay in?",
            "number_of_guests": "How many guests?",
        }
        st.session_state.chat_messages.append({"role": "assistant", "content": prompts[ask]})
        st.rerun()
        return None
    else:
        # Optional clarifications (one pass)
        if "asked_optional" not in st.session_state:
            st.session_state.asked_optional = True
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": "Great. Any preferred property type (apartment, house, studio, cabin, penthouse, hotel), a budget per night, or must-have amenities?"
            })
            st.rerun()
            return None

        # Return a clean preferences dict once we have the essentials
        return {
            "location": prefs["location"],
            "number_of_guests": prefs["number_of_guests"],
            "property_type": prefs["property_type"],
            "budget": prefs["budget"],
            "amenities": prefs["amenities"],
        }

def _ingest(text: str) -> None:
    """
    Super-light extraction from free text. You can replace with your
    LLM-based extractor if desired.
    """
    t = text.lower()

    # guests
    import re
    guests = None
    m = re.search(r"(\d+)\s*(guest|guests|people|persons|ppl)", t)
    if m:
        guests = int(m.group(1))
    elif t.strip().isdigit():
        guests = int(t.strip())

    # city (very naive; look for capitalized token from a small list you use)
    cities = ["montreal", "quebec city", "quebec", "toronto", "magog", "ottawa", "vancouver"]
    city = None
    for c in cities:
        if c in t:
            city = "quebec city" if c == "quebec" else c
            break

    # property type
    ptypes = ["apartment", "house", "studio", "cabin", "penthouse", "hotel"]
    ptype = None
    for p in ptypes:
        if p in t:
            ptype = p
            break

    # budget
    m2 = re.search(r"\$?\s*(\d+)\s*(per night|night|/night|cad|usd|dollars)?", t)
    budget = int(m2.group(1)) if m2 else None

    # amenities
    amen_words = ["wifi", "parking", "pool", "air conditioning", "kitchen", "washer", "dryer", "heating"]
    amens = [a for a in amen_words if a in t]

    prefs = st.session_state.collected_prefs
    if city: prefs["location"] = city.title()
    if guests: prefs["number_of_guests"] = guests
    if ptype: prefs["property_type"] = ptype
    if budget: prefs["budget"] = budget
    if amens:
        # merge unique
        current = set(prefs["amenities"] or [])
        prefs["amenities"] = list(current.union(amens))
