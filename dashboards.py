# dashboards.py
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans

def price_distribution(df: pd.DataFrame):
    st.subheader("Price Distribution")
    fig, ax = plt.subplots()
    ax.hist(df["price"].dropna(), bins=30)
    ax.set_xlabel("Price")
    ax.set_ylabel("Count")
    st.pyplot(fig, clear_figure=True)

def avg_price_by_city(df: pd.DataFrame):
    st.subheader("Average Price by City")
    city_price = df.groupby("city")["price"].mean().sort_values(ascending=False).head(20)
    fig, ax = plt.subplots()
    city_price.plot(kind="bar", ax=ax)
    ax.set_xlabel("City")
    ax.set_ylabel("Avg Price")
    st.pyplot(fig, clear_figure=True)

def location_clusters(df: pd.DataFrame, k: int = 5):
    if not {"latitude", "longitude"}.issubset(df.columns):
        st.info("No latitude/longitude columns found to cluster locations.")
        return
    st.subheader("Location Clusters (K-Means)")
    coords = df[["latitude", "longitude"]].dropna()
    if coords.empty:
        st.info("No coordinates to cluster.")
        return
    k = min(k, len(coords)) if len(coords) > 0 else 1
    kmeans = KMeans(n_clusters=max(1, k), n_init="auto", random_state=42)
    labels = kmeans.fit_predict(coords)
    fig, ax = plt.subplots()
    scatter = ax.scatter(coords["longitude"], coords["latitude"], c=labels)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"{k} Clusters")
    st.pyplot(fig, clear_figure=True)

def dashboards_page(listings: pd.DataFrame, reservations: pd.DataFrame):
    st.header("Analytics Dashboard")
    col1, col2 = st.columns(2)
    with col1:
        price_distribution(listings)
    with col2:
        avg_price_by_city(listings)
    st.divider()
    location_clusters(listings, k=5)
