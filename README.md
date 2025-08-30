# Vacation Rental Recommender

This project is an AI-powered vacation rental recommender system inspired by Airbnb. It integrates a recommendation engine, property images from Unsplash, and user authentication.

## 📂 Project Structure

- `agent.py` – Core AI agent logic
- `auth.py` – Authentication setup
- `auth_config.yaml` – Authentication configuration (⚠️ Do not commit to GitHub)
- `listings1.csv` – Dataset of rental listings
- `reservations.csv` – Stores reservations made by users
- `recommender.py` – Recommendation engine
- `main.py` – Backend entry point (FastAPI/Flask app)
- `streamlit_app.py` – Streamlit UI entry point
- `ui_frontend.py` – Frontend UI logic
- `unsplash_Images.py` – Unsplash API image helper

## 🚀 Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/Peter-Salame23/AirBnB_Agentic_Chatbot
cd vacation-recommender
```

### 2. Create a virtual environment & install dependencies
```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the project root:
```env
UNSPLASH_ACCESS_KEY=your_unsplash_key
SECRET_KEY=your_secret_key
```


### 4. Run the Streamlit App
```bash
streamlit run streamlit_app.py
```

## 🔐 Authentication
- `auth_config.yaml` stores demo users and login details.
- ⚠️ Keep this file private. Add it to `.gitignore`.

## ⚡ Notes
- Ensure `listings1.csv` and `reservations.csv` are in the project root.
- Update `unsplash_Images.py` with your Unsplash API key.
- Both **backend** and **Streamlit frontend** can run together if integrated.

---

With everything set up, you’ll have a recommender system that authenticates users, fetches images from Unsplash, and suggests vacation rentals interactively!
