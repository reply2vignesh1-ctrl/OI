import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests
from datetime import datetime

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Live NIFTY OI Radar", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Live NIFTY Options OI Dashboard")

if 'morning_anchor' not in st.session_state:
    st.session_state.morning_anchor = None

# ==========================================
# SIDEBAR: CONTROLS
# ==========================================
with st.sidebar:
    st.header("🔄 Live Data Controls")
    
    if st.button("Fetch Live NSE Data", use_container_width=True):
        st.session_state.fetch_now = True
        
    st.markdown("---")
    st.header("⏱️ Session Comparison")
    if st.button("📸 Set Current Data as Morning Anchor"):
        st.session_state.set_anchor_flag = True
    else:
        st.session_state.set_anchor_flag = False
        
    if st.session_state.morning_anchor is not None:
        st.success("Morning anchor saved! Comparison chart is active.")
        if st.button("Clear Anchor"):
            st.session_state.morning_anchor = None
            st.rerun()

# ==========================================
# NSE API SCRAPER
# ==========================================
def fetch_nse_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br"
    }
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5) # Get cookies
        response = session.get(url, headers=headers, timeout=5)
        data = response.json()
        
        records = []
        for item in data['records']['data']:
            strike = item.get('strikePrice')
            ce = item.get('CE', {})
            pe = item.get('PE', {})
            
            records.append({
                'STRIKE': strike,
                'CE_OI': ce.get('openInterest', 0) / 100000.0 if ce.get('openInterest') else 0,
                'CE_CHG_OI': ce.get('changeinOpenInterest', 0) / 100000.0 if ce.get('changeinOpenInterest') else 0,
                'CE_LTP': ce.get('lastPrice', 0),
                'PE_OI': pe.get('openInterest', 0) / 100000.0 if pe.get('openInterest') else 0,
                'PE_CHG_OI': pe.get('changeinOpenInterest', 0) / 100000.0 if pe.get('changeinOpenInterest') else 0,
                'PE_LTP': pe.get('lastPrice', 0)
            })
        return pd.DataFrame(records).sort_values('STRIKE').reset_index(drop=True)
    except Exception as e:
        st.error(f"Failed to fetch data from NSE. Please try clicking refresh again. Error: {e}")
        return None

# ==========================================
# MAIN EXECUTION
# ==========================================
df = fetch_nse_data()

if df is not None and not df.empty:
    st.success(f"Live NSE data fetched successfully at {datetime.now().strftime('%H:%M:%S')}")

    # Save Morning Anchor if button was clicked
    if st.session_state.set_anchor_flag:
        st.session_state.morning_anchor = df.copy()
        st.rerun()

    # ==========================================
    # KEY CALCULATIONS
    # ==========================================
    v_ltp = df[(df['CE_LTP'] > 0) & (df['PE_LTP'] > 0)].copy()
    
    if v_ltp.empty:
        df['_TOTAL_OI'] = df['CE_OI'] + df['PE_OI']
        atm_strike = int(df.loc[df['_TOTAL_OI'].idxmax(), 'STRIKE'])
        implied_fwd = atm_strike
        straddle_prem = 0
    else:
        v_ltp['DIFF'] = (v_ltp['CE_LTP'] - v_ltp['PE_LTP']).abs()
        atm_r = v_ltp.loc[v_ltp['DIFF'].idxmin()]
        atm_strike = int(atm_r['STRIKE'])
        implied_fwd = round(atm_strike + (atm_r['CE_LTP'] - atm_r['PE_LTP']), 1)
        straddle_prem = round(atm_r['CE_LTP'] + atm_r['PE_LTP'], 1)

    macro_ce_strike = int(df.loc[df['CE_OI'].idxmax(), 'STRIKE'])
    macro_pe_strike = int(df.loc[df['PE_OI'].idxmax(), 'STRIKE'])

    st.subheader("📊 Key Market Levels")
    col1, col2, col3 = st.columns(3)
    col1.metric("ATM Strike", atm_strike)
    col2.metric("Implied Forward", implied_fwd)
    col3.metric("Straddle Premium", f"Rs. {straddle_prem}")

    # ==========================================
    # CHART 1: TUG OF WAR
    # ==========================================
    st.subheader("⚔️ Tug-of-War OI Radar (±300 Pts)")
    df_zoom = df[(df['STRIKE'] >= atm_strike - 300) & (df['STRIKE'] <= atm_strike + 300)].copy()
    
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        y=df_zoom['STRIKE'], x=-df_zoom['CE_OI'],
        orientation='h', name='🔴 Call OI', marker_color='#ef4444',
        text=[f"<b>{oi:.2f}L</b>" for oi in df_zoom['CE_OI']], textposition='outside'
    ))
    fig1.add_trace(go.Bar(
        y=df_zoom['STRIKE'], x=df_zoom['PE_OI'],
        orientation='h', name='🟢 Put OI', marker_color='#22c55e',
        text=[f"<b>{oi:.2f}L</b>" for oi in df_zoom['PE_OI']], textposition='outside'
    ))
    fig1.add_hline(y=atm_strike, line_dash="dash", line_color="#facc15")
    fig1.add_vline(x=0, line_width=2, line_color="#ffffff")
    fig1.update_layout(barmode='overlay', height=600, xaxis=dict(title="Calls ◄ | ► Puts"))
    st.plotly_chart(fig1, use_container_width=True)

    # ==========================================
    # CHART 2: ACTION BOARD
    # ==========================================
    st.subheader("📋 Today's Change in OI")
    board = df_zoom.copy()
    board['NET_FLOW'] = board['PE_CHG_OI'] - board['CE_CHG_OI']
    
    word_labels = []
    for _, r in board.iterrows():
        net = r['NET_FLOW']
        if net >= 0.35: action = "🟢 STRONG PUT FLOOR BUILT"
        elif net >= 0.12: action = "🟢 Mild Put Support"
        elif net <= -0.35: action = "🔴 HEAVY CALL CEILING BUILT"
        elif net <= -0.12: action = "🔴 Mild Call Resistance"
        else: action = "⚪ Balanced Fight"
        word_labels.append(f"<b>{net:+.2f}L</b> → {action}")

    bar_colors = ['#22c55e' if v >= 0 else '#ef4444' for v in board['NET_FLOW']]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        y=board['STRIKE'], x=board['NET_FLOW'], orientation='h',
        marker_color=bar_colors, text=word_labels, textposition='outside'
    ))
    fig2.add_hline(y=atm_strike, line_dash="dash", line_color="#facc15")
    fig2.update_layout(height=600, xaxis=dict(title="Bearish ◄ | ► Bullish"))
    st.plotly_chart(fig2, use_container_width=True)
