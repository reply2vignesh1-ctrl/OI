import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
from datetime import datetime

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="NIFTY OI Radar", layout="wide", initial_sidebar_state="expanded")
st.title("🎯 NIFTY Options OI Dashboard")

# ==========================================
# HELPER FUNCTIONS (From Import Data.txt)
# ==========================================
def clean_num(val):
    if pd.isna(val): return 0.0
    s = str(val).replace(',', '').replace('-', '').strip()
    try: return float(s) if s not in ['-', '', 'nan', 'None'] else 0.0
    except ValueError: return 0.0

def load_nse_snapshot(file_bytes):
    text = file_bytes.decode('utf-8', errors='ignore')
    lines = text.splitlines()
    hdr = next((i for i, l in enumerate(lines[:30]) if 'STRIKE' in l.upper() and 'OI' in l.upper()), None)
    
    if hdr is None:
        st.error("⚠️ Could not find Option Chain columns in the uploaded file.")
        return None
        
    raw_df = pd.read_csv(io.StringIO("\n".join(lines[hdr:])), on_bad_lines='skip')
    
    d = pd.DataFrame()
    d['STRIKE'] = raw_df.iloc[:, 11].apply(clean_num)
    d['CE_OI']  = raw_df.iloc[:, 1].apply(clean_num) / 100000.0
    d['CE_CHG_OI'] = raw_df.iloc[:, 2].apply(clean_num) / 100000.0
    d['CE_LTP'] = raw_df.iloc[:, 5].apply(clean_num)
    d['PE_LTP'] = raw_df.iloc[:, 17].apply(clean_num)
    d['PE_CHG_OI'] = raw_df.iloc[:, 20].apply(clean_num) / 100000.0
    d['PE_OI']  = raw_df.iloc[:, 21].apply(clean_num) / 100000.0
    
    return d[d['STRIKE'] > 0].sort_values('STRIKE').reset_index(drop=True)

# ==========================================
# SIDEBAR: FILE UPLOADERS (Replaces Master Loader)
# ==========================================
with st.sidebar:
    st.header("📂 Data Upload")
    am_file = st.file_uploader("1. Upload Morning/Current CSV", type=['csv'])
    pm_file = st.file_uploader("2. Upload Afternoon CSV (Optional)", type=['csv'])
    
    st.markdown("---")
    st.info("Upload just the first file for a live snapshot. Upload both to see Midday Session Comparisons.")

# ==========================================
# MAIN EXECUTION
# ==========================================
if am_file is not None:
    df_am = load_nse_snapshot(am_file.getvalue())
    
    if df_am is not None:
        # --- KEY CALCULATIONS ---
        df = df_am.copy()
        v_ltp = df[(df['CE_LTP'] > 0) & (df['PE_LTP'] > 0)].copy()
        
        if v_ltp.empty:
            st.warning("No valid LTP data — using max total OI strike as ATM proxy")
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

        # Print Metrics Box
        st.subheader("📊 Key Market Levels")
        col1, col2, col3 = st.columns(3)
        col1.metric("ATM Strike", atm_strike)
        col2.metric("Implied Forward", implied_fwd)
        col3.metric("Straddle Premium", f"Rs. {straddle_prem}")
        
        st.markdown(f"**MACRO WALLS:** Put Floor = {macro_pe_strike} | Call Ceiling = {macro_ce_strike}")
        st.markdown("---")

        # --- TUG-OF-WAR CHART ---
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

        # --- PLAIN ENGLISH ACTION BOARD ---
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

        # --- MIDDAY SESSION COMPARISON (If 2nd file is uploaded) ---
        if pm_file is not None:
            st.markdown("---")
            st.subheader("⏱️ Pure Midday Session Comparison")
            df_pm = load_nse_snapshot(pm_file.getvalue())
            
            merged = pd.merge(
                df_am[['STRIKE', 'CE_OI', 'PE_OI']], df_pm[['STRIKE', 'CE_OI', 'PE_OI']],
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
            
else:
    st.info("👈 Please upload an NSE Option Chain CSV file in the sidebar to begin.")