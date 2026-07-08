import streamlit as st
import time
import json
import os
import re
import html
import requests
import xml.etree.ElementTree as ET
import pandas as pd

# ================== CONFIG ==================
OWNER_EMAILS = [
    "hajiannugraha@gmail.com",
    "hajianclashofclans@gmail.com",
    "widya.nurulmustofa@gmail.com"
]

# Sumber berita: Google News RSS search, per saham. Ini dipakai (bukan RSS
# portal lokal seperti Kontan) karena formatnya publik, terdokumentasi, dan
# stabil: https://news.google.com/rss/search?q=<query>&hl=id&gl=ID&ceid=ID:id
# Setiap saham punya query sendiri, jadi berita yang didapat SUDAH PASTI
# relevan dengan saham itu (tidak perlu tebak-tebak lewat keyword matching
# di teks umum, yang lebih rawan salah cocok).
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
STOCK_NEWS_QUERIES = {
    "ADRO": "Adaro Energy saham",
    "BRIS": "Bank Syariah Indonesia saham",
    "TLKM": "Telkom Indonesia saham",
}

# Kata kunci sederhana untuk menilai sentimen berita. Ini pendekatan
# berbasis kata kunci (bukan AI/NLP model), jadi masih bisa kurang akurat
# untuk kalimat yang ambigu atau bernada sarkasme.
POSITIVE_KEYWORDS = [
    "naik", "menguat", "profit", "laba", "untung", "melesat", "rekor",
    "akuisisi", "ekspansi", "dividen", "buyback", "tumbuh", "positif",
    "melonjak", "meningkat", "surplus", "upgrade",
]
NEGATIVE_KEYWORDS = [
    "turun", "melemah", "rugi", "anjlok", "gugatan", "delisting",
    "penurunan", "downgrade", "default", "phk", "bangkrut", "negatif",
    "tersendat", "tertekan", "net sell", "koreksi",
]

# File tempat menyimpan status langganan agar TIDAK hilang setiap kali
# Streamlit menjalankan ulang script (yang terjadi di HAMPIR setiap interaksi).
# Ini masih penyimpanan lokal sederhana (bukan database asli), tapi jauh lebih
# aman daripada dict biasa yang direset tiap rerun.
USER_DB_FILE = "user_db.json"


def load_user_db():
    if os.path.exists(USER_DB_FILE):
        try:
            with open(USER_DB_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_user_db(db):
    with open(USER_DB_FILE, "w") as f:
        json.dump(db, f)


# ================== NEWS FETCHING ==================
# ttl=55 supaya cache berita ikut "segar" tiap kali auto-refresh (60 detik)
# atau manual refresh terjadi, tanpa membombardir Google News tiap rerun kecil.
@st.cache_data(ttl=55, show_spinner=False)
def fetch_stock_news(ticker, query, max_items=5):
    params = {"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AITradingTerminal/1.0)"}
    articles = []
    try:
        resp = requests.get(GOOGLE_NEWS_RSS_BASE, params=params, headers=headers, timeout=8)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item")[:max_items]:
            title = html.unescape((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            description = html.unescape(re.sub("<[^<]+?>", "", description))
            pub_date = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source = (source_el.text or "").strip() if source_el is not None else ""
            articles.append({
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
                "source": source,
            })
    except (requests.RequestException, ET.ParseError):
        # Kalau Google News lagi tidak bisa diakses/timeout, kembalikan list
        # kosong untuk saham ini daripada bikin seluruh app error.
        pass
    return articles


def analyze_sentiment(text):
    text_lower = text.lower()
    pos_hits = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
    neg_hits = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)
    if pos_hits > neg_hits:
        return "POSITIF", "🟢"
    elif neg_hits > pos_hits:
        return "NEGATIF", "🔴"
    else:
        return "NETRAL", "⚪"


def parse_pub_date(pub_date_str):
    """Untuk mengurutkan berita dari yang terbaru. Kalau format tanggal
    tidak dikenali, taruh di paling bawah daripada bikin app crash."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_date_str)
    except (TypeError, ValueError):
        import datetime
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def get_all_stock_news(stock_queries, max_items_per_stock=5):
    """Ambil berita untuk tiap saham di watchlist, tandai sentimennya, lalu
    gabungkan semua dan urutkan dari yang paling baru."""
    all_news = []
    for ticker, query in stock_queries.items():
        articles = fetch_stock_news(ticker, query, max_items_per_stock)
        for article in articles:
            combined_text = f"{article['title']} {article['description']}"
            sentiment, emoji = analyze_sentiment(combined_text)
            all_news.append({
                **article,
                "matched_stocks": [ticker],
                "sentiment": sentiment,
                "sentiment_emoji": emoji,
            })
    all_news.sort(key=lambda a: parse_pub_date(a["pub_date"]), reverse=True)
    return all_news


# ================== AUTH ==================
st.title("🚀 AI IDX Trading Terminal PRO")

# CATATAN PENTING: ini bukan autentikasi asli. Siapa pun bisa mengetik email
# apa saja (termasuk email owner) dan langsung dianggap sah, karena tidak ada
# verifikasi password/OTP/magic-link. Untuk produksi, ini WAJIB diganti dengan
# autentikasi sungguhan (misal Firebase Auth, Supabase Auth, atau
# st.experimental_user + OAuth) sebelum aplikasi ini menerima uang dari user.
email = st.text_input("Login pakai email")


def get_user_status(email, user_db):
    if email in OWNER_EMAILS:
        return "owner"
    return user_db.get(email, {}).get("status", "inactive")


if email:
    user_db = load_user_db()
    status = get_user_status(email, user_db)

    if status == "owner":
        st.success("👑 Owner access granted")
    elif status == "active":
        st.success("✅ Subscription aktif")
    else:
        st.warning("❌ Belum berlangganan")
        st.stop()
else:
    st.stop()

# ================== REFRESH ==================
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

col1, col2 = st.columns(2)

with col1:
    if st.button("🔄 Manual Refresh", use_container_width=True):
        st.rerun()

with col2:
    auto_label = "⏸️ Matikan Auto Refresh" if st.session_state.auto_refresh else "⚡ Aktifkan Auto Refresh"
    if st.button(auto_label, use_container_width=True):
        st.session_state.auto_refresh = not st.session_state.auto_refresh
        st.rerun()

if st.session_state.auto_refresh:
    st.caption("⏱️ Auto refresh aktif — halaman akan reload tiap 60 detik")
    # PENTING: sebelumnya pakai time.sleep(60) + st.rerun(), yang MEMBLOKIR
    # seluruh server thread selama 60 detik (app jadi 'freeze' total).
    # Ini diganti dengan meta-refresh HTML yang jalan di sisi browser,
    # jadi server tetap responsif untuk request lain.
    st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)

# ================== MODE ==================
mode = st.radio("Mode", ["Elite", "Alert", "Bandar"])

# CATATAN: data ini masih dummy/hardcoded (cuma 3 saham). Untuk data real-time
# perlu integrasi ke API bursa (misal IDX, Yahoo Finance, atau data provider lain).
data = pd.DataFrame({
    "stock": ["ADRO.JK", "BRIS.JK", "TLKM.JK"],
    "score": [80, 65, 72],
    "bandar": ["AKUMULASI", "-", "AKUMULASI"],
})

data["stock"] = data["stock"].str.replace(".JK", "", regex=False)


# ================== SIGNAL LOGIC ==================
def get_signal(bandar):
    if bandar == "AKUMULASI":
        return "🟢 BUY"
    elif bandar == "MARKUP":
        return "💰 TAKE PROFIT"
    elif bandar == "DISTRIBUSI":
        return "🔴 SELL"
    else:
        return "-"


data["signal"] = data["bandar"].apply(get_signal)

if mode == "Elite":
    df = data.sort_values(by="score", ascending=False)
elif mode == "Alert":
    df = data[data["score"] > 70]
else:
    df = data[data["bandar"] == "AKUMULASI"]

st.dataframe(df)

# ================== ALERT ==================
alert_df = df[(df["score"] > 70) & (df["bandar"] == "AKUMULASI")]
if not alert_df.empty:
    # Sebelumnya hanya menampilkan alert_df.iloc[0] (satu saham saja).
    # Sekarang menampilkan SEMUA saham yang memenuhi kriteria.
    tickers = ", ".join(alert_df["stock"].tolist())
    st.warning(f"🚨 {tickers} — potensi lanjut / momentum tinggi (cek TAKE PROFIT)")

# ================== NEWS ==================
st.subheader("📰 Berita Saham Terkini")

# Berita ini otomatis ikut ter-update setiap kali app rerun — baik lewat
# klik "Manual Refresh" maupun auto-refresh 60 detik di atas — karena
# get_all_stock_news() dipanggil ulang tiap rerun. Cache ttl=55 detik
# mencegah request ke Google News berulang-ulang dalam waktu singkat.
with st.spinner("Mengambil berita terbaru..."):
    news_items = get_all_stock_news(STOCK_NEWS_QUERIES)

if not news_items:
    st.info(
        "Belum ada berita terbaru untuk saham di watchlist kamu "
        "(ADRO, BRIS, TLKM), atau Google News sedang tidak bisa diakses."
    )
else:
    for news in news_items:
        stocks_str = ", ".join(news["matched_stocks"])
        with st.container(border=True):
            st.markdown(f"**{news['title']}**")
            cols = st.columns([1, 1, 2])
            cols[0].markdown(f"📈 Saham: `{stocks_str}`")
            cols[1].markdown(f"{news['sentiment_emoji']} {news['sentiment']}")
            meta = " · ".join(x for x in [news["source"], news["pub_date"]] if x)
            if meta:
                cols[2].caption(meta)
            if news["description"]:
                st.caption(news["description"][:220] + ("..." if len(news["description"]) > 220 else ""))
            if news["link"]:
                st.markdown(f"[Baca selengkapnya]({news['link']})")

# ================== STRIPE WEBHOOK ==================
# CATATAN PENTING: Streamlit TIDAK BISA menerima HTTP webhook secara langsung
# (tidak ada route/endpoint di app Streamlit). Fungsi di bawah ini hanya
# contoh LOGIKA-nya saja. Untuk implementasi nyata, kamu perlu:
#   1. Server terpisah (Flask/FastAPI) yang punya endpoint /stripe-webhook
#   2. Server itu memverifikasi signature webhook dari Stripe
#   3. Server itu menulis ke USER_DB_FILE (atau database asli seperti
#      Postgres/Supabase) — bukan ke dict Python yang cuma hidup di memory
#   4. App Streamlit ini membaca dari storage yang sama (sudah dilakukan
#      lewat load_user_db() di atas)
def stripe_webhook(event):
    user_db = load_user_db()
    if event["type"] == "checkout.session.completed":
        customer_email = event["data"]["object"]["customer_email"]
        user_db[customer_email] = {"status": "active"}
    elif event["type"] == "invoice.payment_failed":
        customer_email = event["data"]["object"]["customer_email"]
        user_db[customer_email] = {"status": "inactive"}
    save_user_db(user_db)
