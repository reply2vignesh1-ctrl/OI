import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from dhanhq import dhanhq
from streamlit_autorefresh import st_autorefresh

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Live NIFTY OI Radar", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Live NIFTY Options OI Dashboard")

# Initialize Session Memory for Midday Comparison
if 'morning_anchor' not in st.session_state:
    st.session_state.morning_anchor = None

# ==========================================
# SIDEBAR: LIVE API CONNECTION
# ==========================================
with st.sidebar:
    st.header("🔌 Live Broker Connection")
    st.markdown("Enter your DhanHQ API details below. These are not saved to the public code.")
    
    client_id = st.text_input("Client ID", type="password")
    access_token = st.text_input("API Access Token", type="password")
    expiry_date = st.text_input("Expiry Date (YYYY-MM-DD)", value="2026-11-26")
    
    st.markdown("---")
    
    # Auto-refresh timer: 180000 milliseconds = 3 minutes
    st_autorefresh(interval=180000, limit=200, key="data_refresh")
    st.success("🔄 Auto-refreshing every 3 minutes")
    
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
# MAIN EXECUTION: FETCH LIVE DATA
# ==========================================
if client_id and access_token:
    try:
        # 1. Connect to Broker
        dhan = dhanhq(client_id, access_token)
        
        # 2. Fetch Live Option Chain (NIFTY Index = "13")
        raw_chain = dhan.get_option_chain(
            underlying_security_id="13", 
            underlying_type="INDEX", 
            expiry_date=expiry_date 
        )
        
        # 3. Format Data
        df = pd.DataFrame(raw_chain['data'])
        df.rename(columns={
            'strikePrice': 'STRIKE',
            'callOI': 'CE_OI',
            'callChangeInOI': 'CE_CHG_OI',
            'callLTP': 'CE_LTP',
            'putLTP': 'PE_LTP',
            'putChangeInOI': 'PE_CHG_OI',
            'putOI': 'PE_OI'
        }, inplace=True)
        
        # Scale down to Lakhs
        for col in ['CE_OI', 'CE_CHG_OI', 'PE_OI', 'PE_CHG_OI']:
            df[col] = df[col] / 100000.0
            
        df = df[df['STRIKE'] > 0].sort_values('STRIKE').reset_index(drop=True)
        
        st.success(f"Live data fetched successfully at {datetime.now().strftime('%H:%M:%S')}")

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

        # Metrics Box
        st.subheader("📊 Key Market Levels")
        col1, col2, col3 = st.columns(3)
        col1.metric("ATM Strike", atm_strike)
        col2.metric("Implied Forward", implied_fwd)
        col3.metric("Straddle Premium", f"Rs. {straddle_prem}")
        st.markdown(f"**MACRO WALLS:** Put Floor = {macro_pe_strike} | Call Ceiling = {macro_ce_strike}")
        st.markdown("---")

        # ==========================================
        # CHART 1: TUG OF WAR
        # ==========================================
        st.subheader("⚔️ Tug-of-War OI Radar (±300 Pts)")
        df_zoom = df[(df['STRIKE'] >= atm_strike - 300) & (df['STRIKE'] <= atm_strike + 300)].copy()
        
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            y=df_zoom['STRIKE'], x=-df_zoom['CE_OI'],
            orientation='h', name='🔴 Call OI (Ceiling)', marker_color='#ef4444',
            text=[f"<b>{oi:.2f}L</b>" for oi in df_zoom['CE_OI']],
            textposition='outside', textfont=dict(size=12)
        ))
        fig1.add_trace(go.Bar(
            y=df_zoom['STRIKE'], x=df_zoom['PE_OI'],
            orientation='h', name='🟢 Put OI (Floor)', marker_color='#22c55e',
            text=[f"<b>{oi:.2f}L</b>" for oi in df_zoom['PE_OI']],
            textposition='outside', textfont=dict(size=12)
        ))
        fig1.add_hline(y=atm_strike, line_dash="dash", line_color="#facc15", line_width=2)
        fig1.add_vline(x=0, line_width=2, line_color="#ffffff")
        
        max_side = max(df_zoom['CE_OI'].max(), df_zoom['PE_OI'].max()) * 1.45
        fig1.update_layout(
            barmode='overlay', height=600,
            xaxis=dict(range=[-max_side, max_side], title="Call Resistance ◄  |  ► Put Support"),
            yaxis=dict(title="Strike Price", dtick=50),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig1, use_container_width=True)

        # ==========================================
        # CHART 2: ACTION BOARD
        # ==========================================
        st.subheader("📋 Today's Change in OI (Action Board)")
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
        max_x2 = max(board['NET_FLOW'].abs().max(), 0.2) * 2.35
        fig2.update_layout(
            height=600, xaxis=dict(range=[-max_x2, max_x2], title="Bears (Call Writing) ◄ | ► Bulls (Put Writing)"),
            yaxis=dict(dtick=50), margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig2, use_container_width=True)

        # ==========================================
        # CHART 3: MIDDAY SESSION COMPARISON
        # ==========================================
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
                elif net_d <= -0.10: text = "Net Call Built"
                else: text = "Minimal Change"
                labels.append(f"<b>{net_d:+.2f}L</b> → {text}")

            colors3 = ['#22c55e' if v >= 0 else '#ef4444' for v in m_view['NET_DELTA']]
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                y=m_view['STRIKE'], x=m_view['NET_DELTA'], orientation='h',
                marker_color=colors3, text=labels, textposition='outside'
            ))
            fig3.add_hline(y=atm_strike, line_dash="dash", line_color="#facc15")
            max_x3 = max(m_view['NET_DELTA'].abs().max(), 0.15) * 2.10
            fig3.update_layout(
                height=600, xaxis=dict(range=[-max_x3, max_x3], title="Net Call Add ◄ | ► Net Put Add"),
                yaxis=dict(dtick=50), margin=dict(l=0, r=0, t=30, b=0)
            )
            st.plotly_chart(fig3, use_container_width=True)

    except Exception as e:
        st.error(f"Failed to fetch live data: {e}. Please check your API credentials and expiry date format.")
else:
    st.info("👈 Enter your DhanHQ API credentials and the current Expiry Date in the sidebar to start the live feed.")
