"""Small presentation layer; retain native Streamlit controls and semantics."""
import streamlit as st


def apply_theme():
    st.markdown('''<style>
    .stApp { color: #202c35; }
    .block-container { max-width: 1480px; padding-top: 2.1rem; padding-bottom: 3rem; }
    [data-testid="stSidebar"] { border-right: 1px solid #e3e8eb; }
    [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
    h1 { font-size: 2rem !important; font-weight: 650 !important; letter-spacing: -0.025em; }
    h2 { font-size: 1.35rem !important; font-weight: 620 !important; }
    h3 { font-size: 1.1rem !important; font-weight: 600 !important; }
    p, label { line-height: 1.55; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #586671 !important; }
    [data-testid="stCaptionContainer"] { opacity: 1 !important; }
    input::placeholder, textarea::placeholder { color: #65717a !important; opacity: 1; }
    button, input, textarea { caret-color: #16756b; }
    button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible {
      outline: 2px solid #16756b !important; outline-offset: 3px;
    }
    ::selection { background: #d2ebe5; color: #143f39; }
    [data-testid="stMetricValue"] { font-size: 1.65rem; font-variant-numeric: tabular-nums; }
    [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
    [data-baseweb="tab-list"] { gap: 1.4rem; }
    [data-baseweb="tab"] { padding-left: 0; padding-right: 0; }
    @media (max-width: 640px) {
      .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1rem; }
      h1 { font-size: 1.65rem !important; }
      [data-baseweb="tab-list"] { gap: 1rem; }
    }
    </style>''', unsafe_allow_html=True)
