import streamlit as st
import os
import json

# Set up the Page Layout
st.set_page_config(page_title="SACC Control Panel", layout="wide")

st.title("👟 Sneaker AI Control Panel")
st.sidebar.header("Navigation")
mode = st.sidebar.radio("Go to:", ["Control Panel (Process)", "Search Vault (Data)"])

# --- TAB 1: CONTROL PANEL ---
if mode == "Control Panel (Process)":
    st.header("Video Processing Pipeline")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Raw Videos", "42")
        if st.button("Step 1: Rename Files"):
            st.write("Renaming logic started...")
            
    with col2:
        st.metric("To Compress", "12")
        if st.button("Step 2: Run Squeezer"):
            st.progress(30, text="Compressing C0104.mp4...")
            
    with col3:
        st.metric("API Pending", "8")
        if st.button("Step 3: Submit to AI"):
            st.success("Sent to Gemini!")

# --- TAB 2: SEARCH VAULT ---
else:
    st.header("Search Your Collection")
    search_query = st.text_input("Search by Name, SKU, or Color", placeholder="e.g. Chicago")
    
    # Mock data to show you how it looks
    st.subheader("Results")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.image("https://images.stockx.com/360/Air-Jordan-1-Retro-High-White-University-Blue-Black/Images/Air-Jordan-1-Retro-High-White-University-Blue-Black/Lv2/img01.jpg", width=200)
    with c2:
        st.write("**Model:** Jordan 1 University Blue")
        st.write("**SKU:** 555088-134")
        st.write("**Status:** ✅ JSON Verified")
        if st.button("Play Original 4K Video"):
            st.info("Opening local file...")