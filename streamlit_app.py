# streamlit_app.py
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from auth import gate  # <-- Auth gate
from agent import BookingAgent
from recommender import Recommender
from ui_frontend import render_recommendations  # cards with images

# ---------------- UI ----------------
st.set_page_config(page_title="Dr. House — Booking Agent", page_icon="🧳", layout="wide")

# --------------- AUTH ---------------
name, auth_status, username, authenticator = gate()
if not auth_status:
    st.info("Please log in above to continue.")
    st.stop()

# ---------------- Helpers & State ----------------
def init_state():
    if "booking_agent" not in st.session_state:
        st.session_state.booking_agent = BookingAgent()
    if "recommender" not in st.session_state:
        st.session_state.recommender = Recommender(csv_path="listings.csv")
    if "stage" not in st.session_state:
        # collect -> choose -> confirm_book -> idle
        st.session_state.stage = "collect"
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "last_criteria" not in st.session_state:
        st.session_state.last_criteria = None
    if "last_recs" not in st.session_state:
        st.session_state.last_recs = []
    if "pending_listing_id" not in st.session_state:
        st.session_state.pending_listing_id = None
    if "selected_listing" not in st.session_state:
        st.session_state.selected_listing = None  # full listing dict at selection time
    if "show_recs" not in st.session_state:
        st.session_state.show_recs = False  # only true when stage == "choose"

def say(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})

def render_chat():
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

def try_parse_selection(user_input: str, recs):
    """Return listing_id or None. Accepts 'book 2', 'book id 55', 'select 3', or just '2'."""
    s = user_input.strip().lower()
    m = re.search(r"(book|select)\s+(id\s+)?(\d+)$", s)
    if m:
        num = int(m.group(3))
        ids = [int(r["listing_id"]) for r in recs if "listing_id" in r]
        if num in ids:
            return num
        if 1 <= num <= len(recs):  # index
            return int(recs[num-1]["listing_id"])
        return None
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= len(recs):
            return int(recs[idx-1]["listing_id"])
    return None

def hide_recs():
    st.session_state.show_recs = False
    st.session_state.last_recs = []
    st.session_state.pending_listing_id = None

def end_flow(msg: str):
    hide_recs()
    st.session_state.stage = "idle"
    say("assistant", msg + " Type **restart** to start a new search.")

def reset_all():
    st.session_state.booking_agent = BookingAgent()
    st.session_state.recommender = Recommender(csv_path="listings.csv")
    st.session_state.stage = "collect"
    st.session_state.messages = []
    st.session_state.last_criteria = None
    st.session_state.last_recs = []
    st.session_state.pending_listing_id = None
    st.session_state.selected_listing = None
    st.session_state.show_recs = False

def current_listing_id():
    lid = st.session_state.get("pending_listing_id")
    if lid is not None:
        try:
            return int(lid)
        except Exception:
            pass
    sel = st.session_state.get("selected_listing")
    if sel and sel.get("listing_id") is not None:
        try:
            return int(sel["listing_id"])
        except Exception:
            pass
    return None

# ---------- Init after successful auth ----------
init_state()

# ---------- Sidebar ----------
with st.sidebar:
    st.title("🧳 Dr. House — Booking Agent")
    st.caption("Chat to pick a place, then book it. Type *restart* to start over.")
    st.divider()

    st.success(f"Logged in as: {name} (@{username})")
    authenticator.logout("Logout", location="sidebar")

    # --- My Reservations (per-user) ---
    st.subheader("📒 My Reservations")
    res_path = Path("reservations.csv")
    if res_path.exists() and res_path.stat().st_size > 0:
        try:
            res_df = pd.read_csv(res_path)
        except pd.errors.EmptyDataError:
            res_df = pd.DataFrame()
        except Exception as e:
            st.warning(f"Could not load reservations.csv: {e}")
            res_df = pd.DataFrame()
    else:
        res_df = pd.DataFrame()

    if not res_df.empty and "username" in res_df.columns:
        my_df = res_df[res_df["username"] == username].copy()
    else:
        my_df = pd.DataFrame()

    if not my_df.empty:
        my_df = my_df.sort_values("created_utc", ascending=False).reset_index(drop=True)
        st.dataframe(my_df, use_container_width=True, height=280)
        st.download_button(
            "Download my reservations (CSV)",
            data=my_df.to_csv(index=False),
            file_name=f"my_reservations_{username}.csv",
            mime="text/csv",
        )
    else:
        st.info("No reservations yet for your account.")

    # Admin: reset reservations / unbook listings
    st.divider()
    st.subheader("⚙️ Admin")
    with st.form("reset_reservations_form", clear_on_submit=False):
        st.markdown("**Reset all reservations**")
        also_unbook = st.checkbox("Also mark reserved listings as Available in listings.csv", value=True)
        confirm_text = st.text_input("Type CONFIRM to proceed", value="")
        submitted = st.form_submit_button("🗑️ Reset reservations")

    if submitted:
        if confirm_text.strip().upper() != "CONFIRM":
            st.warning("Type CONFIRM exactly to proceed.")
        else:
            # Clear reservations file (write empty with headers for future robustness)
            try:
                pd.DataFrame(columns=[
                    "reservation_id","listing_id","name","location","property_type",
                    "price_per_night","rating","reviews_count","amenities",
                    "guest_name","guest_email","date_checkin","date_checkout",
                    "number_of_guests","nights","estimated_total","status",
                    "created_utc","username"
                ]).to_csv(res_path, index=False)
                st.success("reservations.csv cleared.")
            except Exception as e:
                st.error(f"Failed clearing reservations.csv: {e}")

            # Optionally unbook listings
            if also_unbook:
                try:
                    lst_path = Path("listings.csv")
                    if lst_path.exists():
                        lst_df = pd.read_csv(lst_path)
                        if "availability" in lst_df.columns:
                            lst_df["availability"] = "Available"
                            lst_df.to_csv(lst_path, index=False)
                            st.success("All listings marked Available.")
                        else:
                            st.warning("listings.csv missing 'availability' column.")
                    else:
                        st.warning("listings.csv not found; cannot unbook listings.")
                except Exception as e:
                    st.error(f"Failed to unbook listings: {e}")

            # reload recommender so it sees updated listings.csv
            st.session_state.recommender = Recommender(csv_path="listings.csv")
            say("assistant", "Reservations reset. Start fresh anytime!")
            st.rerun()

    st.divider()
    if st.button("🔄 Restart conversation"):
        reset_all()
        st.rerun()

# Header + chat so far
st.markdown("### Hello! I'm **Dr. House**, your booking agent. How can I help you plan your stay?")
render_chat()

# ---- Recommendations panel (only when choosing and allowed) ----
if st.session_state.stage == "choose" and st.session_state.last_recs and st.session_state.show_recs:
    selected_id = render_recommendations(st.session_state.last_recs, columns=3)
    if selected_id is not None:
        chosen = next(
            (r for r in st.session_state.last_recs if str(r.get("listing_id")) == str(selected_id)),
            None
        )
        st.session_state.pending_listing_id = selected_id
        st.session_state.selected_listing = chosen
        hide_recs()
        if chosen:
            say("assistant", f"Great choice! **{chosen.get('name')}** (ID `{chosen.get('listing_id')}`)")
        # Go straight to confirm step (no name/email prompts)
        crit = st.session_state.last_criteria or {}
        say(
            "assistant",
            (
                "**Please confirm the reservation details:**\n"
                f"- Listing: **{(chosen or {}).get('name','(unknown)')}** (ID `{(chosen or {}).get('listing_id','?')}`)\n"
                f"- Location: {(chosen or {}).get('location','?')} | Type: {(chosen or {}).get('property_type','?')}\n"
                f"- Check-in: {crit.get('date_checkin')} | Check-out: {crit.get('date_checkout')} | Guests: {crit.get('number_of_guests')}\n"
                f"- Price per night: {(chosen or {}).get('price_per_night','?')} *(taxes/fees may apply)*\n\n"
                "Type **yes** to confirm or **no** to cancel."
            )
        )
        st.session_state.stage = "confirm_book"
        st.rerun()

# ---- Chat input ----
user_text = st.chat_input("Type your message…")
if user_text is not None:
    # Basic commands
    if user_text.strip().lower() in {"quit", "exit"}:
        say("user", user_text)
        end_flow("No problem—ping me anytime. Bye!")
        st.rerun()

    if user_text.strip().lower() in {"restart", "new"}:
        say("user", user_text)
        reset_all()
        say("assistant", "Fresh start! Tell me what you’re looking for.")
        st.rerun()

    # If in idle, only allow restart/new
    if st.session_state.stage == "idle":
        say("user", user_text)
        say("assistant", "We’re all set. Type **restart** to begin a new search.")
        st.rerun()

    # Normal flow
    say("user", user_text)
    stage = st.session_state.stage
    agent = st.session_state.booking_agent
    rec = st.session_state.recommender

    # ----- Stage: collect or choose (refine) -----
    if stage in {"collect", "choose"}:
        if stage == "choose":
            listing_id = try_parse_selection(user_text, st.session_state.last_recs)
            if listing_id is not None:
                st.session_state.pending_listing_id = listing_id
                chosen = next(
                    (r for r in st.session_state.last_recs if str(r.get("listing_id")) == str(listing_id)),
                    None
                )
                st.session_state.selected_listing = chosen
                hide_recs()
                crit = st.session_state.last_criteria or {}
                say(
                    "assistant",
                    (
                        "**Please confirm the reservation details:**\n"
                        f"- Listing: **{(chosen or {}).get('name','(unknown)')}** (ID `{(chosen or {}).get('listing_id','?')}`)\n"
                        f"- Location: {(chosen or {}).get('location','?')} | Type: {(chosen or {}).get('property_type','?')}\n"
                        f"- Check-in: {crit.get('date_checkin')} | Check-out: {crit.get('date_checkout')} | Guests: {crit.get('number_of_guests')}\n"
                        f"- Price per night: {(chosen or {}).get('price_per_night','?')}\n\n"
                        "Type **yes** to confirm or **no** to cancel."
                    )
                )
                st.session_state.stage = "confirm_book"
                st.rerun()

        # Otherwise, let the agent process user text
        agent_reply = agent.run(user_text)
        if agent_reply.strip().startswith("{") and agent_reply.strip().endswith("}"):
            try:
                st.session_state.last_criteria = json.loads(agent_reply)
            except Exception:
                say("assistant", "I had trouble reading your preferences JSON. Mind repeating?")
                st.rerun()

            st.session_state.last_recs = rec.recommend(st.session_state.last_criteria, top_k=5)
            if st.session_state.last_recs:
                say("assistant", "I found options — open the **Recommended options** panel above to review and book.")
                st.session_state.stage = "choose"
                st.session_state.show_recs = True
            else:
                say("assistant", "No matches with those filters. Try loosening location/type/amenities.")
                st.session_state.stage = "collect"
                st.session_state.show_recs = False
        else:
            say("assistant", agent_reply)

    # ----- Stage: confirm_book -----
    elif stage == "confirm_book":
        s = user_text.strip().lower()
        if s not in {"yes", "y", "no", "n"}:
            say("assistant", "Please reply **yes** to confirm or **no** to cancel.")
        elif s in {"no", "n"}:
            end_flow("No problem. Reservation canceled.")
        else:
            lid = current_listing_id()
            if lid is None:
                say("assistant", "Hmm, I lost the selected property. Please pick it again from the list.")
                st.session_state.stage = "choose"
                st.session_state.show_recs = True
                st.rerun()

            # Confirm => reserve (book under account; no name/email prompts)
            try:
                reservation = st.session_state.recommender.reserve(
                    listing_id=lid,
                    criteria=st.session_state.last_criteria,
                    customer={},                  # no prompts needed
                    username=username,            # key for per-user view
                )
                say(
                    "assistant",
                    (
                        "✅ **Reservation confirmed!**\n"
                        f"- Reservation ID: `{reservation['reservation_id']}`\n"
                        f"- {reservation['name']} — {reservation['property_type']} in {reservation['location']}\n"
                        f"- Check-in: {reservation['date_checkin']} | Check-out: {reservation['date_checkout']} | Nights: {reservation['nights']}\n"
                        f"- Guests: {reservation['number_of_guests']}\n"
                        f"- Estimated total: **{reservation['estimated_total']}**"
                    )
                )
                if reservation.get("warning"):
                    say("assistant", f"Note: {reservation['warning']}")
                end_flow("Booked!")
            except Exception as e:
                say("assistant", f"Couldn't complete the reservation: {e}")
                say("assistant", "Want to pick another option or refine filters?")
                st.session_state.stage = "choose"
                st.session_state.show_recs = False

    st.rerun()
