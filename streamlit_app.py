# streamlit_app.py
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from agent import BookingAgent
from recommender import Recommender
from ui_frontend import render_recommendations  # cards with images

# ---------------- Helpers & State ----------------
def init_state():
    if "booking_agent" not in st.session_state:
        st.session_state.booking_agent = BookingAgent()
    if "recommender" not in st.session_state:
        st.session_state.recommender = Recommender(csv_path="listings.csv")
    if "stage" not in st.session_state:
        # collect -> choose -> confirm_name -> confirm_email -> confirm_book -> idle
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
        st.session_state.selected_listing = None  # store the full listing dict at selection time
    if "customer" not in st.session_state:
        st.session_state.customer = {"name": None, "email": None}
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
    # keep selected_listing for confirmation; clear pending until selection sets it
    st.session_state.pending_listing_id = None

def end_flow(msg: str):
    # Clean up after booking/cancel so the panel can’t render again
    hide_recs()
    st.session_state.stage = "idle"   # final state until user restarts
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
    st.session_state.customer = {"name": None, "email": None}
    st.session_state.show_recs = False

def current_listing_id():
    """Return a safe listing_id from session, or None."""
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

# ---------------- UI ----------------
st.set_page_config(page_title="Dr. House — Booking Agent", page_icon="🧳", layout="wide")
init_state()

with st.sidebar:
    st.title("🧳 Dr. House — Booking Agent")
    st.caption("Chat to pick a place, then book it. Type *restart* to start over.")
    st.divider()

    # Reservations viewer
    res_path = Path("reservations.csv")
    if res_path.exists():
        try:
            res_df = pd.read_csv(res_path)
            st.subheader("📒 Reservations")
            st.dataframe(
                res_df.sort_values("created_utc", ascending=False),
                use_container_width=True,
                height=280,
            )
            st.download_button(
                "Download reservations.csv",
                data=res_df.to_csv(index=False),
                file_name="reservations.csv",
                mime="text/csv",
            )
        except Exception as e:
            st.warning(f"Could not load reservations.csv: {e}")
    else:
        st.info("No reservations yet.")

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
            if res_path.exists():
                try:
                    prev_res_df = pd.read_csv(res_path)
                except Exception:
                    prev_res_df = None
                pd.DataFrame().to_csv(res_path, index=False)
                st.success("reservations.csv cleared.")
            else:
                prev_res_df = None
                st.info("No reservations.csv found to clear.")

            if also_unbook and prev_res_df is not None and not prev_res_df.empty:
                try:
                    lst_path = Path("listings.csv")
                    if lst_path.exists():
                        lst_df = pd.read_csv(lst_path)
                        if "listing_id" in lst_df.columns and "availability" in lst_df.columns:
                            reserved_ids = set(prev_res_df["listing_id"].astype(str).tolist())
                            mask = lst_df["listing_id"].astype(str).isin(reserved_ids)
                            lst_df.loc[mask, "availability"] = "Available"
                            lst_df.to_csv(lst_path, index=False)
                            st.success(f"Unbooked {mask.sum()} listing(s) in listings.csv.")
                        else:
                            st.warning("listings.csv missing required columns (listing_id / availability).")
                    else:
                        st.warning("listings.csv not found; cannot unbook listings.")
                except Exception as e:
                    st.error(f"Failed to unbook listings: {e}")

            # reload recommender so it sees updated listings.csv
            st.session_state.recommender = Recommender(csv_path="listings.csv")
            say("assistant", "🧹 Reservations reset. Start fresh anytime!")
            st.experimental_rerun()

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
        # Store chosen listing now (so later steps don't depend on last_recs)
        chosen = next(
            (r for r in st.session_state.last_recs if str(r.get("listing_id")) == str(selected_id)),
            None
        )
        st.session_state.pending_listing_id = selected_id
        st.session_state.selected_listing = chosen
        hide_recs()  # hide during identity collection
        if chosen:
            say("assistant", f"Great choice! **{chosen.get('name')}** (ID `{chosen.get('listing_id')}`)")
        else:
            say("assistant", "Great choice! (Selected property)")
        say("assistant", "Please share your **full name** for the reservation.")
        st.session_state.stage = "confirm_name"
        st.rerun()

# ---- Chat input ----
user_text = st.chat_input("Type your message…")
if user_text is not None:
    # Basic commands
    if user_text.strip().lower() in {"quit", "exit"}:
        say("user", user_text)
        end_flow("No problem—ping me anytime. Bye! 👋")
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
        # If we're in choose, allow quick 'book <n>' or 'book id <id>'
        if stage == "choose":
            listing_id = try_parse_selection(user_text, st.session_state.last_recs)
            if listing_id is not None:
                st.session_state.pending_listing_id = listing_id
                chosen = next(
                    (r for r in st.session_state.last_recs if str(r.get("listing_id")) == str(listing_id)),
                    None
                )
                st.session_state.selected_listing = chosen
                hide_recs()  # hide during identity collection
                say("assistant", "Great choice! Please share your **full name** for the reservation.")
                st.session_state.stage = "confirm_name"
                st.rerun()

        # Otherwise, let the agent process user text
        agent_reply = agent.run(user_text)
        if agent_reply.strip().startswith("{") and agent_reply.strip().endswith("}"):
            # Completed criteria => recommend
            try:
                st.session_state.last_criteria = json.loads(agent_reply)
            except Exception:
                say("assistant", "I had trouble reading your preferences JSON. Mind repeating?")
                st.rerun()

            st.session_state.last_recs = rec.recommend(st.session_state.last_criteria, top_k=5)
            if st.session_state.last_recs:
                # Show list ONLY in the panel, not in chat (prevents re-display later)
                say("assistant", "I found options — open the **Recommended options** panel above to review and book.")
                st.session_state.stage = "choose"
                st.session_state.show_recs = True
            else:
                say("assistant", "No matches with those filters. Try loosening location/type/amenities.")
                st.session_state.stage = "collect"
                st.session_state.show_recs = False
        else:
            # The agent is asking a follow-up question
            say("assistant", agent_reply)

    # ----- Stage: confirm_name -----
    elif stage == "confirm_name":
        name = user_text.strip()
        if not name:
            say("assistant", "Please provide a **name** to continue.")
        else:
            st.session_state.customer["name"] = name
            say("assistant", "Thanks! And your **email**?")
            st.session_state.stage = "confirm_email"

    # ----- Stage: confirm_email -----
    elif stage == "confirm_email":
        email = user_text.strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            say("assistant", "Could you provide a **valid email**?")
        else:
            st.session_state.customer["email"] = email

            # Use the saved listing (never None after selection). If somehow None, recover from DF.
            chosen = st.session_state.selected_listing
            if not chosen:
                try:
                    lid = current_listing_id()
                    if lid is not None:
                        row = st.session_state.recommender.df[
                            st.session_state.recommender.df["listing_id"].astype(str) == str(lid)
                        ]
                        chosen = row.iloc[0].to_dict() if not row.empty else {}
                        st.session_state.selected_listing = chosen
                    else:
                        chosen = {}
                except Exception:
                    chosen = {}

            crit = st.session_state.last_criteria or {}
            say(
                "assistant",
                (
                    "**Please confirm the reservation details:**\n"
                    f"- Listing: **{chosen.get('name','(unknown)')}** (ID `{chosen.get('listing_id','?')}`)\n"
                    f"- Location: {chosen.get('location','?')} | Type: {chosen.get('property_type','?')}\n"
                    f"- Check-in: {crit.get('date_checkin')} | Check-out: {crit.get('date_checkout')} | Guests: {crit.get('number_of_guests')}\n"
                    f"- Price per night: {chosen.get('price_per_night','?')} *(taxes/fees may apply)*\n\n"
                    "Type **yes** to confirm or **no** to cancel."
                )
            )
            st.session_state.stage = "confirm_book"

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

            # Confirm => reserve
            try:
                reservation = st.session_state.recommender.reserve(
                    listing_id=lid,
                    criteria=st.session_state.last_criteria,
                    customer=st.session_state.customer
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
                # keep user in choose, but do NOT show recs automatically
                st.session_state.stage = "choose"
                st.session_state.show_recs = False

    # Persist chat on screen, then rerun to update UI
    st.rerun()
