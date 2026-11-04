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
        # Generate the login link
        session = fyersModel.SessionModel(
            client_id=app_id, secret_key=secret_id, 
            redirect_uri="https://127.0.0.1", response_type='code', grant_type='authorization_code'
        )
        auth_link = session.generate_authcode()
        
        st.markdown(f"**Step 1:** [Click here to Login to FYERS]({auth_link})")
        st.caption("After logging in, you will be redirected to an error page (127.0.0.1). This is normal! Just copy the entire URL from your browser's address bar.")
        
        auth_input = st.text_input("**Step 2:** Paste the Redirect URL here:")
        
        if st.button("Connect App", use_container_width=True):
            try:
                # Parse the auth code out of the pasted URL
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
    expiry_format = st.text_input("Expiry Symbol Format", value="26N05", help="Format: YY + Month(N/O/D) + DD. Example: 26N05 for Nov 5 2026")
    
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
        # 1. Get NIFTY 50 LTP to find the ATM strike
        idx_resp = fyers.quotes({"symbols": "NSE:NIFTY50-INDEX"})
        if 'd' not in idx_resp or not idx_resp['d']:
            st.error("Failed to fetch NIFTY Index. Check API connection.")
            return None
            
        nifty_ltp = idx_resp['d'][0]['v']['lp']
        atm = int(round(nifty_ltp / 50.0)) * 50
        
        # 2. Build symbols for Option Chain (ATM ± 400 points)
        strikes = range(atm - 400, atm + 450, 50)
        symbols = [f"NSE:NIFTY{exp_fmt}{s}CE" for s in strikes] + [f"NSE:NIFTY{exp_fmt}{s}PE" for s in strikes]
        
        # 3. Fetch Quotes in chunks (Fyers max is 50 symbols per request)
        records = []
        for i in range(0, len(symbols), 50):
            chunk = symbols[i:i+50]
            resp = fyers.quotes({"symbols": ",".join(chunk)})
            
            if 'd' in resp:
                for q in resp['d']:
                    sym = q['n']
                    v = q['v']
                    opt_type = sym[-2:] # CE or PE
                    strike = int(sym.replace(f"NSE:NIFTY{exp_fmt}", "").replace(opt_type, ""))
                    
                    records.append({
                        'STRIKE': strike,
                        'TYPE': opt_type,
                        'OI': v.get('oi', 0) / 100000.0,
                        'LTP': v.get('lp', 0)
                    })
                    
        # 4. Format into our Dashboard DataFrame
        df_raw = pd.DataFrame(records)
        ce_df = df_raw[df_raw['TYPE'] == 'CE'].rename(columns={'OI': 'CE_OI', 'LTP': 'CE_LTP'}).drop('TYPE', axis=1)
        pe_df = df_raw[df_raw['TYPE'] == 'PE'].rename(columns={'OI': 'PE_OI', 'LTP': 'PE_LTP'}).drop('TYPE', axis=1)
        
        df = pd.merge(ce_df, pe_df, on='STRIKE', how='outer').fillna(0).sort_values('STRIKE').reset_index(drop=True)
        
        # Fyers Quotes API does not provide previous day OI directly, so intraday change is held at 0.
        # The Anchor Comparison Chart will still calculate exact Session Changes perfectly!
        df['CE_CHG_OI'] = 0  
        df['PE_CHG_OI'] = 0
        
        return df
    except Exception as e:
        st.error(f"Fyers API Error: {e}")
        return None

# ==========================================
# MAIN EXECUTION
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

    # CHART 2: SESSION COMPARISON (The most important chart!)
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
        max_x3 = max(m_view['NET_DELTA'].abs().max(), 0.15) * 2.10 if not m_view.empty else 1
        fig3.update_layout(height=600, xaxis=dict(range=[-max_x3, max_x3], title="Net Call Add ◄ | ► Net Put Add"))
        st.plotly_chart(fig3, use_container_width=True)

else:
    st.info("👈 Login to FYERS in the sidebar and click 'Fetch Live Data'.")
