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

# Initialize Session States
if 'morning_anchor' not in st.session_state:
    st.session_state.morning_anchor = None
if 'live_df' not in st.session_state:
    st.session_state.live_df = None
if 'fetch_now' not in st.session_state:
    st.session_state.fetch_now = False

# ==========================================
# SIDEBAR: CONTROLS
# ==========================================
with st.sidebar:
    st.header("🔌 Live Broker Connection")
    st.markdown("*(Direct REST API Connection)*")
    
    client_id = st.text_input("Client ID", type="password")
    access_token = st.text_input("API Access Token", type="password")
    expiry_date = st.text_input("Expiry Date (YYYY-MM-DD)", value="2026-11-05")
    
    if st.button("Fetch Live Data", use_container_width=True):
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
# DHAN DIRECT REST API
# ==========================================
def fetch_dhan_rest_api(cid, token, exp):
    url = "https://api.dhan.co/v2/optionchain"
    headers = {
        "client-id": cid,
        "access-token": token,
        "Content-Type": "application/json"
    }
    payload = {
        "UnderlyingScrip": 13,
        "UnderlyingSeg": "IDX_I",
        "Expiry": exp
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            st.error(f"Broker API Error: {response.text}")
            return None
            
        data = response.json()
        records = []
        
        # Navigate Dhan's raw JSON structure
        oc_data = data.get('data', {}).get('oc', {})
        
        for strike_str, options in oc_data.items():
            strike = float(strike_str)
            ce = options.get('ce', {})
            pe = options.get('pe', {})
            
            # Calculate Intraday Change in OI (Current - Previous)
            ce_oi = ce.get('oi', 0)
            ce_chg_oi = ce_oi - ce.get('previous_oi', 0)
            
            pe_oi = pe.get('oi', 0)
            pe_chg_oi = pe_oi - pe.get('previous_oi', 0)
            
            records.append({
                'STRIKE': strike,
                'CE_OI': ce_oi / 100000.0,
                'CE_CHG_OI': ce_chg_oi / 100000.0,
                'CE_LTP': ce.get('last_price', 0),
                'PE_OI': pe_oi / 100000.0,
                'PE_CHG_OI': pe_chg_oi / 100000.0,
                'PE_LTP': pe.get('last_price', 0)
            })
            
        return pd.DataFrame(records).sort_values('STRIKE').reset_index(drop=True)
        
    except Exception as e:
        st.error(f"Failed to parse broker data. Error: {e}")
        return None

# ==========================================
# MAIN EXECUTION
# ==========================================
# Only fetch from broker when the button is clicked
if st.session_state.fetch_now and client_id and access_token:
    st.session_state.live_df = fetch_dhan_rest_api(client_id, access_token, expiry_date)
    st.session_state.fetch_now = False # Reset trigger

df = st.session_state.live_df

if df is not None and not df.empty:
    st.success(f"Dashboard updated. Displaying latest fetched data.")

    if st.session_state.set_anchor_flag:
        st.session_state.morning_anchor = df.copy()
        st.session_state.set_anchor_flag = False
        st.rerun()

    # KEY CALCULATIONS
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

    # CHART 1: TUG OF WAR
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
    max_side = max(df_zoom['CE_OI'].max(), df_zoom['PE_OI'].max()) * 1.45 if not df_zoom.empty else 1
    fig1.update_layout(barmode='overlay', height=600, xaxis=dict(range=[-max_side, max_side], title="Calls ◄ | ► Puts"))
    st.plotly_chart(fig1, use_container_width=True)

    # CHART 2: ACTION BOARD
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
    max_x2 = max(board['NET_FLOW'].abs().max(), 0.2) * 2.35 if not board.empty else 1
    fig2.update_layout(height=600, xaxis=dict(range=[-max_x2, max_x2], title="Bearish ◄ | ► Bullish"))
    st.plotly_chart(fig2, use_container_width=True)
    
    # CHART 3: SESSION COMPARISON
    if st.session_state.morning_anchor is not None:
        st.markdown("---")
        st.subheader("⏱️ Pure Midday Session Comparison (Anchor vs Live)")
        
        df_am = st.session_state.morning_anchor
        merged = pd.merge(
            df_am[['STRIKE', 'CE_OI', 'PE_OI']], df[['STRIKE', 'CE_OI', 'PE_OI']],
            on='STRIKE', suffixes=('_AM', '_PM')
        )
        merged['CE_DELTA'] = merged['CE_OI_PM'] - merged['CE_OI_AM']
        merged['PE_DELTA'] = merged['PE_OI_PM'] - merged['PE_OI_AM']
        merged['NET_DELTA'] = merged['PE_DELTA'] - merged['CE_DELTA']
        
        m_view = merged[(merged['STRIKE'] >= atm_strike - 300) & (merged['STRIKE'] <= atm_strike + 300)]
        
        labels = []
        for _, r in m_view.iterrows():
            net_d = r['NET_DELTA']
            if net_d >= 0.10: text = "Net Put Built"
            elif net_d <= -0.1:
