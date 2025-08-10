import json
import re
from agent import BookingAgent
from recommender import Recommender

def pretty_print_recs(recs):
    if not recs:
        print("\nDr. House: I couldn't find exact matches. Want to adjust filters (dates, area, amenities)?")
        return
    print("\n⭐ Top options for you:")
    for i, r in enumerate(recs, start=1):
        print(f"\n[{i}] {r.get('name','N/A')} — {r.get('property_type','N/A')} in {r.get('location','N/A')}")
        print(f"    Listing ID: {r.get('listing_id','N/A')}")
        print(f"    Price/night: {r.get('price_per_night','N/A')} | Rating: {r.get('rating','N/A')} ({r.get('reviews_count','N/A')} reviews)")
        print(f"    Bedrooms: {r.get('bedrooms','N/A')}")
        print(f"    Amenities: {r.get('amenities','N/A')}")

def try_parse_selection(user_input: str, recs):
    """Return chosen listing_id or None. Accepts 'book 2', 'book id 55', 'select 3', or just '2'."""
    s = user_input.strip().lower()
    m = re.search(r"(book|select)\s+(id\s+)?(\d+)$", s)
    if m:
        num = int(m.group(3))
        ids = [int(r["listing_id"]) for r in recs if "listing_id" in r]
        if num in ids:
            return num
        if 1 <= num <= len(recs):  # treat as index
            return int(recs[num-1]["listing_id"])
        return None
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= len(recs):
            return int(recs[idx-1]["listing_id"])
    return None

def main():
    print("Script started...")
    try:
        booking_agent = BookingAgent()
        recommender = Recommender(csv_path="listings.csv")
        print("BookingAgent initialized.")
        print("Hello! I'm Dr. House, your booking agent. How can I help you plan your stay?")

        # FSM
        stage = "collect"           # collect -> recommend -> choose -> confirm_name -> confirm_email -> confirm_book
        last_criteria = None
        last_recs = []
        pending_listing_id = None
        customer = {"name": None, "email": None}

        while True:
            user_input = input("You: ").strip()
            if user_input == "":
                continue
            if user_input.lower() in {"quit", "exit"}:
                print("Dr. House: No problem—ping me anytime. Bye!")
                break
            if user_input.lower() in {"new", "restart"}:
                # reset everything
                booking_agent = BookingAgent()
                stage = "collect"
                last_criteria = None
                last_recs = []
                pending_listing_id = None
                customer = {"name": None, "email": None}
                print("Dr. House: Fresh start! Tell me what you’re looking for.")
                continue

            # ---- STAGES ----
            if stage == "collect":
                # Normal collection: call agent; if JSON, recommend; else ask next question
                response = booking_agent.run(user_input)
                if response.strip().startswith("{") and response.strip().endswith("}"):
                    try:
                        last_criteria = json.loads(response)
                    except Exception:
                        print("Dr. House: I had trouble reading your preferences JSON. Mind repeating?")
                        continue
                    last_recs = recommender.recommend(last_criteria, top_k=5)
                    pretty_print_recs(last_recs)
                    print("\nDr. House: You can refine (e.g., 'make it Old Montreal', 'add pool', 'change dates to 2025-08-20 to 2025-08-25'),")
                    print("or book by saying 'book 1' or 'book id <listing_id>'. Type 'new' to start over, or 'quit' to exit.")
                    stage = "choose"
                else:
                    print("Dr. House:", response)

            elif stage == "choose":
                # Either booking selection or refinement
                listing_id = try_parse_selection(user_input, last_recs)
                if listing_id is not None:
                    pending_listing_id = listing_id
                    print("Dr. House: Great choice! Please share your full name for the reservation.")
                    stage = "confirm_name"
                    continue

                # Otherwise treat as refinement: feed back to agent to update criteria
                response = booking_agent.run(user_input)
                if response.strip().startswith("{") and response.strip().endswith("}"):
                    last_criteria = json.loads(response)
                    last_recs = recommender.recommend(last_criteria, top_k=5)
                    pretty_print_recs(last_recs)
                    if last_recs:
                        print("\nDr. House: Refined! Say 'book 1' (or 'book id <listing_id>') to reserve, or keep refining.")
                    else:
                        print("\nDr. House: No matches with those filters. Try loosening location/type/amenities.")
                else:
                    # Agent asked a clarifying Q (should be rare after completion)
                    print("Dr. House:", response)

            elif stage == "confirm_name":
                customer["name"] = user_input
                if not customer["name"]:
                    print("Dr. House: Please provide a name to continue.")
                    continue
                print("Dr. House: Thanks! And your email?")
                stage = "confirm_email"

            elif stage == "confirm_email":
                if "@" not in user_input or "." not in user_input.split("@")[-1]:
                    print("Dr. House: Could you provide a valid email?")
                    continue
                customer["email"] = user_input

                chosen = next((r for r in last_recs if int(r["listing_id"]) == int(pending_listing_id)), None)
                print("\nDr. House: Please confirm the reservation details:")
                print(f"  Listing: {chosen.get('name')} (ID {chosen.get('listing_id')})")
                print(f"  Location: {chosen.get('location')} | Type: {chosen.get('property_type')}")
                print(f"  Check-in: {last_criteria.get('date_checkin')} | Check-out: {last_criteria.get('date_checkout')} | Guests: {last_criteria.get('number_of_guests')}")
                print(f"  Price per night: {chosen.get('price_per_night')} (taxes/fees may apply)")
                print("Type 'yes' to confirm or 'no' to cancel.")
                stage = "confirm_book"

            elif stage == "confirm_book":
                s = user_input.strip().lower()
                if s not in {"yes", "y", "no", "n"}:
                    print("Dr. House: Please reply 'yes' to confirm or 'no' to cancel.")
                    continue
                if s in {"no", "n"}:
                    print("Dr. House: No problem. Want to choose another option?")
                    stage = "choose"
                    continue

                # Confirm → reserve
                try:
                    reservation = recommender.reserve(
                        listing_id=pending_listing_id,
                        criteria=last_criteria,
                        customer=customer
                    )
                    print("\n✅ Reservation confirmed!")
                    print(f"  Reservation ID: {reservation['reservation_id']}")
                    print(f"  {reservation['name']} — {reservation['property_type']} in {reservation['location']}")
                    print(f"  Check-in: {reservation['date_checkin']} | Check-out: {reservation['date_checkout']} | Nights: {reservation['nights']}")
                    print(f"  Guests: {reservation['number_of_guests']}")
                    print(f"  Estimated total: {reservation['estimated_total']}")
                    if reservation.get("warning"):
                        print(f"  Note: {reservation['warning']}")
                    print("\nDr. House: Booked! You can type 'new' to start a new search, or 'quit' to exit.")
                    # stay live; allow new searches
                    stage = "choose"
                except Exception as e:
                    print(f"Dr. House: Couldn't complete the reservation: {e}")
                    print("Dr. House: Want to pick another option or refine filters?")
                    stage = "choose"

    except KeyboardInterrupt:
        print("\nDr. House: Caught Ctrl+C — goodbye!")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
print("hello")
