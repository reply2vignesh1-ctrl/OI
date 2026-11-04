import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from fyers_apiv3 import fyersModel
from datetime import datetime

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Live NIFTY OI Radar", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 Live NIFTY Options OI Dashboard (FYERS)")

# Initialize Session States
if 'morning_anchor' not in st.session_state:
    st.session_state.morning_anchor = None
if 'live_df' not in st.session_state:
    st.session_state.live_df = None
if 'fyers_access_token' not in st.session_state:
    st.session_state.fyers_access_token = None
if 'fetch_now' not in st.session_state:
    st.session_state.fetch_now = False

# ==========================================
# SIDEBAR: CONTROLS & AUTH
# ==========================================
with st.sidebar:
    st.header("🔌 FYERS Live Connection")
    
    app_id = st.text_input("App ID", value="BJ5M8T24YW-200")
    secret_id = st.text_input("Secret ID", type="password")
    
    st.markdown("### 🔐 Authentication")
    if app_id and secret_id:
        session = fyersModel.SessionModel(
            client_id=app_id, secret_key=secret_id, 
            redirect_uri="https://127.0.0.1", response_type='code', grant_type='authorization_code'
        )
        auth_link = session.generate_authcode()
        
        st.markdown(f"**Step 1:** [Click here to Login to FYERS]({auth_link})")
        st.caption("After logging in, you will be redirected to an error page (127.0.0.1). Copy the entire URL from your address bar.")
        
        auth_input = st.text_input("**Step 2:** Paste the Redirect URL here:")
        
        if st.button("Connect App", use_container_width=True):
            try:
                if "auth_code=" in auth_input:
                    code = auth_input.split("auth_code=")[1].split("&")[0]
                else:
                    code = auth_input
                    
                session.set_token(code)
                response = session.generate_token()
                st.session_state.fyers_access_token = response['access_token']
                st.success("✅ Connected successfully!")
            except Exception as e:
                st.error("Connection failed. Check your Secret ID and URL.")

    st.markdown("---")
    st.header("🔄 Fetch Data")
    expiry_format = st.text_input("Expiry Symbol Format", value="26N05")
    
    if st.button("Fetch Live Data", use_container_width=True):
        st.session_state.fetch_now = True
        
    st.markdown("---")
    st.header("⏱️ Session Comparison")
    if st.button("📸 Set Current Data as Morning Anchor"):
        st.session_state.set_anchor_flag = True
    else:
        st.session_state.set_anchor_flag = False
        
    if st.session_state.morning_anchor is not None:
        st.success("Morning anchor saved! Comparison active.")
        if st.button("Clear Anchor"):
            st.session_state.morning_anchor = None
            st.rerun()

# ==========================================
# FYERS DATA FETCHER
# ==========================================
def fetch_fyers_oc(client_id, access_token, exp_fmt):
    fyers = fyersModel.FyersModel(client_id=client_id, token=access_token, is_async=False, log_path="")
    
    try:
        # 1. Fetch Spot Index temporarily just to center our strike window
        idx_resp = fyers.quotes({"symbols": "NSE:NIFTY50-INDEX"})
        if 'd' not in idx_resp or not idx_resp['d']:
            st.error("Failed to fetch NIFTY Index.")
            return None
            
        spot = idx_resp['d'][0]['v']['lp']
        center_strike = int(round(spot / 50.0)) * 50
        
        # 2. Build wide Option Chain (ATM ± 1000 points) to ensure True Implied ATM is captured
        strikes = range(center_strike - 1000, center_strike + 1050, 50)
        symbols = [f"NSE:NIFTY{exp_fmt}{s}CE" for s in strikes] + [f"NSE:NIFTY{exp_fmt}{s}PE" for s in strikes]
        
        # 3. Fetch in chunks (Fyers limit is 50 symbols per request)
        records = []
        for i in range(0, len(symbols), 50):
            chunk = symbols[i:i+50]
            resp = fyers.quotes({"symbols": ",".join(chunk)})
            
            if 'd' in resp:
                for q in resp['d']:
                    sym = q['n']
                    v = q['v']
                    opt_type = sym[-2:] 
                    strike = int(sym.replace(f"NSE:NIFTY{exp_fmt}", "").replace(opt_type, ""))
                    
                    # Extract FYERS Previous Day OI (pdoi) for True Intraday Change in OI
                    current_oi = v.get('oi', 0)
                    prev_oi = v.get('pdoi', current_oi) 
                    chg_oi = current_oi - prev_oi
                    
                    records.append({
                        'STRIKE': strike,
                        'TYPE': opt_type,
                        'OI': current_oi / 100000.0,
                        'CHG_OI': chg_oi / 100000.0,
                        'LTP': v.get('lp', 0)
                    })
                    
        # 4. Format DataFrame
        df_raw = pd.DataFrame(records)
        ce_df = df_raw[df_raw['TYPE'] == 'CE'].rename(columns={'OI': 'CE_OI', 'CHG_OI': 'CE_CHG_OI', 'LTP': 'CE_LTP'}).drop('TYPE', axis=1)
        pe_df = df_raw[df_raw['TYPE'] == 'PE'].rename(columns={'OI': 'PE_OI', 'CHG_OI': 'PE_CHG_OI', 'LTP': 'PE_LTP'}).drop('TYPE', axis=1)
        
        df = pd.merge(ce_df, pe_df, on='STRIKE', how='outer').fillna(0).sort_values('STRIKE').reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Fyers API Error: {e}")
        return None

# ==========================================
# MAIN EXECUTION & QUANTITATIVE ENGINE
# ==========================================
if st.session_state.fetch_now and st.session_state.fyers_access_token:
    st.session_state.live_df = fetch_fyers_oc(app_id, st.session_state.fyers_access_token, expiry_format)
    st.session_state.fetch_now = False

df = st.session_state.live_df

if df is not None and not df.empty:
    st.success(f"Dashboard updated. Displaying latest fetched data.")

    if st.session_state.set_anchor_flag:
        st.session_state.morning_anchor = df.copy()
        st.session_state.set_anchor_flag = False
        st.rerun()

    # ==========================================
    # TRUE IMPLIED ATM & STRADDLE CALCULATIONS
    # ==========================================
    v_ltp = df[(df['CE_LTP'] > 0) & (df['PE_LTP'] > 0)].copy()
    
    if v_ltp.empty:
        st.warning("No active premium data found. Check expiry format.")
        st.stop()
        
    v_ltp['DIFF'] = (v_ltp['CE_LTP'] - v_ltp['PE_LTP']).abs()
    atm_r = v_ltp.loc[v_ltp['DIFF'].idxmin()]
    atm_strike = int(atm_r['STRIKE'])
    
    implied_fwd = round(atm_strike + (atm_r['CE_LTP'] - atm_r['PE_LTP']), 2)
    straddle_prem = round(atm_r['CE_LTP'] + atm_r['PE_LTP'], 2)

    # ==========================================
    # PCR & GREEK-WEIGHTED METRICS
    # ==========================================
    pcr_overall = df['PE_OI'].sum() / df['CE_OI'].sum() if df['CE_OI'].sum() > 0 else 0
    
    df_300 = df[(df['STRIKE'] >= atm_strike - 300) & (df['STRIKE'] <= atm_strike + 300)].copy()
    pcr_300 = df_300['PE_OI'].sum() / df_300['CE_OI'].sum() if df_300['CE_OI'].sum() > 0 else 0
    
    # Rupee/Premium Weighted PCR
    pe_rupee = (df['PE_OI'] * df['PE_LTP']).sum()
    ce_rupee = (df['CE_OI'] * df['CE_LTP']).sum()
    pcr_rupee = pe_rupee / ce_rupee if ce_rupee > 0 else 0

    st.subheader("📊 Key Market Levels & PCR")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ATM Strike (Implied)", atm_strike)
    c2.metric("Implied Forward", implied_fwd)
    c3.metric("Straddle Premium", f"₹ {straddle_prem}")
    c4.metric("PCR (Overall)", round(pcr_overall, 2))
    
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("PCR (± 300 Pts)", round(pcr_300, 2))
    c6.metric("PCR (Rupee Wtd)", round(pcr_rupee, 2))
    c7.metric("Macro Call Ceiling", int(df.loc[df['CE_OI'].idxmax(), 'STRIKE']))
    c8.metric("Macro Put Floor", int(df.loc[df['PE_OI'].idxmax(), 'STRIKE']))

    # ==========================================
    # CHART 1: TUG OF WAR (TOTAL OI)
    # ==========================================
    st.subheader("⚔️ Tug-of-War OI Radar (±300 Pts)")
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        y=df_300['STRIKE'], x=-df_300['CE_OI'],
        orientation='h', name='🔴 Call OI', marker_color='#ef4444',
        text=[f"<b>{oi:.2f}L</b>" for oi in df_300['CE_OI']], textposition='outside'
    ))
    fig1.add_trace(go.Bar(
        y=df_300['STRIKE'], x=df_300['PE_OI'],
        orientation='h', name='🟢 Put OI', marker_color='#22c55e',
        text=[f"<b>{oi:.2f}L</b>" for oi in df_300['PE_OI']], textposition='outside'
    ))
    fig1.add_hline(y=atm_strike, line_dash="dash", line_color="#facc15")
    fig1.add_vline(x=0, line_width=2, line_color="#ffffff")
    max_side1 = max(df_300['CE_OI'].max(), df_300['PE_OI'].max()) * 1.45 if not df_300.empty else 1
    fig1.update_layout(barmode='overlay', height=600, xaxis=dict(range=[-max_side1, max_side1], title="Calls ◄ | ► Puts"))
    st.plotly_chart(fig1, use_container_width=True)

    # ==========================================
    # CHART 2: ACTION BOARD (INTRADAY CHG IN OI)
    # ==========================================
    st.subheader("📋 Today's Change in OI (Action Board)")
    board = df_300.copy()
    board['NET_FLOW'] = board['PE_CHG_OI'] - board['CE_CHG_OI']
    
    word_labels = []
    for _, r in board.iterrows():
        net = r['NET_FLOW']
        if net >= 0.35: action = "🟢 STRONG PUT FLOOR"
        elif net >= 0.12: action = "🟢 Mild Put Support"
        elif net <= -0.35: action = "🔴 HEAVY CALL CEILING"
        elif net <= -0.12: action = "🔴 Mild Call Resist"
        else: action = "⚪ Balanced Flow"
        word_labels.append(f"<b>{net:+.2f}L</b> → {action}")

    bar_colors = ['#22c55e' if v >= 0 else '#ef4444' for v in board['NET_FLOW']]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        y=board['STRIKE'], x=board['NET_FLOW'], orientation='h',
        marker_color=bar_colors, text=word_labels, textposition='outside'
    ))
    fig2.add_hline(y=atm_strike, line_dash="dash", line_color="#facc15")
    max_x2 = max(board['NET_FLOW'].abs().max(), 0.2) * 2.35 if not board.empty else 1
    fig2.update_layout(height=600, xaxis=dict(range=[-max_x2, max_x2], title="Bearish Flow ◄ | ► Bullish Flow"))
    st.plotly_chart(fig2, use_container_width=True)
    
    # ==========================================
    # CHART 3: PURE MIDDAY SESSION COMPARISON
    # ==========================================
    if st.session_state.morning_anchor is not None:
        st.markdown("---")
        st.subheader("⏱️ Session Comparison (Anchor vs Live)")
        
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
        max_x3 = max(m_view['NET_DELTA'].abs().max(), 0.15) * 2.10 if not m_view.empty else 1
        fig3.update_layout(height=600, xaxis=dict(range=[-max_x3, max_x3], title="Net Call Add ◄ | ► Net Put Add"))
        st.plotly_chart(fig3, use_container_width=True)

else:
    st.info("👈 Login to FYERS in the sidebar and click 'Fetch Live Data'.")
