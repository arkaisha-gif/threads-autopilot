import os
import re
import json
import base64
import time
import random
from datetime import datetime, date, time as dtime, timedelta
import pytz
import pandas as pd
import requests
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 🛠️ KONFIGURASI APLIKASI & TEMA
# ==========================================
st.set_page_config(
    page_title="Threads Autopilot & AI Self-Learning Hub",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

TZ = pytz.timezone("Asia/Jakarta")

# Custom CSS untuk tampilan profesional dan ringkas
st.markdown("""
<style>
    .main .block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; font-weight: 700; color: #1E88E5; }
    .status-badge-posted { background-color: #E8F5E9; color: #2E7D32; padding: 4px 8px; border-radius: 4px; font-weight: 600; }
    .status-badge-pending { background-color: #FFF3E0; color: #EF6C00; padding: 4px 8px; border-radius: 4px; font-weight: 600; }
    .status-badge-error { background-color: #FFEBEE; color: #C62828; padding: 4px 8px; border-radius: 4px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 PENGAMBILAN KREDENSIAL & SECRETS
# ==========================================
def get_secret(key, default=""):
    val = os.environ.get(key)
    if val:
        return val
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        try:
            with open(secrets_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith(key):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return default

SPREADSHEET_ID = get_secret("SPREADSHEET_ID", "12HI63liR64ugPz8IHQHy2gAhOOzSDMt0D0-YHO5x08E")
GCP_CREDS_BASE64 = get_secret("GCP_CREDS_BASE64")
AI_API_KEY = get_secret("AI_API_KEY")

@st.cache_resource(ttl=300)
def get_sheets_client():
    raw_creds = str(GCP_CREDS_BASE64).strip() if GCP_CREDS_BASE64 else ""
    if not raw_creds:
        st.error("GCP_CREDS_BASE64 belum disetel di Secrets atau environment!")
        st.stop()
    if raw_creds.startswith("{"):
        info = json.loads(raw_creds)
    elif os.path.exists(raw_creds):
        with open(raw_creds, "r", encoding="utf-8") as f:
            info = json.load(f)
    else:
        decoded = base64.b64decode(raw_creds).decode("utf-8")
        info = json.loads(decoded)

    creds = Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    return gspread.authorize(creds)

def load_all_worksheets():
    client = get_sheets_client()
    sh = client.open_by_key(SPREADSHEET_ID)

    # 1. Sheet data
    ws_data = sh.worksheet("data")
    data_rows = ws_data.get_all_values()
    if len(data_rows) > 1:
        max_cols = max(len(r) for r in data_rows)
        headers = data_rows[0] + [f"col_{i}" for i in range(len(data_rows[0]), max_cols)]
        padded_rows = [r + [""] * (max_cols - len(r)) for r in data_rows[1:]]
        df_data = pd.DataFrame(padded_rows, columns=headers[:max_cols])
    else:
        df_data = pd.DataFrame()

    # 2. Sheet Products
    ws_prods = sh.worksheet("Products")
    p_rows = ws_prods.get_all_records()
    df_prods = pd.DataFrame(p_rows)

    # 3. Sheet Config
    ws_cfg = sh.worksheet("Config")
    c_rows = ws_cfg.get_all_values()
    cfg_map = {r[0].strip(): r[1].strip() for r in c_rows if len(r) >= 2 and r[0].strip()}

    # 4. Sheet Accounts
    ws_acc = sh.worksheet("Accounts")
    a_rows = ws_acc.get_all_records()
    df_acc = pd.DataFrame(a_rows)

    return sh, ws_data, ws_prods, ws_cfg, ws_acc, df_data, df_prods, cfg_map, df_acc

# ==========================================
# 🧠 HELPER AI & COPYWRITING
# ==========================================
THREADS_VIBES = [
    "Capek mental / Realistis: gaya orang lelah yang males ribet, praktis, to the point.",
    "Self-deprecating humor: ngetawain kebiasaan diri sendiri yang dulu repot dan konyol.",
    "Santai ala Close Friends: bahasa tongkrongan santai, celetukan natural, gak ada kesan jualan.",
    "Aesthetic & mindful: fokus ke ketenangan pikiran, kenyamanan ruang, atau kepuasan visual.",
    "Review jujur tanpa filter: lugas, apa adanya, langsung sebut kenapa barang ini ngebantu hidup.",
    "Hot take / observasi santai: mempertanyakan kenapa orang masih ribet pakai cara lama."
]

VIRAL_OBSERVATIONS = [
    "Observasi fenomena absurd atau kebiasaan sepele orang Indonesia sehari-hari.",
    "Dilema umur 20-an ke atas: pertemanan menipis, energi sosial nol, atau culture shock kerja.",
    "Debat sepele tapi bikin dua kubu warganet ribut santai di kolom komentar.",
    "Shower thoughts tengah malam atau kebiasaan aneh yang ternyata dialami banyak orang.",
    "Opini santai tentang hal yang sering diromantisasi padahal aslinya melelahkan."
]

FALLBACK_CTA_STARTERS = [
    "Awas dapet tiruan yang gampang rusak/tumpul ya, link official store yang beneran ori di sini:",
    "Biar gak capek nyari manual ketumpuk seller abal-abal, ambil di lapak resminya di sini:",
    "Sumpah harganya gak masuk akal murahnya wkwk, cek sendiri di sini mumpung diskon:",
    "Buat yang males ribet dan butuh solusinya juga, link toko aslinya di sini ya:"
]

def sanitize_threads_text(text: str, max_chars: int = 495) -> str:
    if not text:
        return ""
    text_str = str(text).strip()
    if len(text_str) > max_chars:
        return text_str[:max_chars - 3].rstrip() + "..."
    return text_str

def call_gemini(prompt: str) -> str:
    key = str(AI_API_KEY).strip().replace("'", "").replace('"', "") if AI_API_KEY else ""
    if not key:
        return "Salah satu barang yang lumayan ngebantu rutinitas harian."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.95, "topP": 0.95, "topK": 40}
    }

    models_to_try = [
        ("v1", "gemini-1.5-flash"),
        ("v1", "gemini-1.5-pro"),
        ("v1beta", "gemini-1.5-flash"),
        ("v1beta", "gemini-2.0-flash")
    ]
    for ver, m_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/{ver}/models/{m_name}:generateContent?key={key}"
        try:
            res = requests.post(url, json=payload, timeout=25).json()
            if "candidates" in res and res["candidates"]:
                out_txt = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if out_txt:
                    return out_txt
        except Exception:
            pass
    return "Salah satu barang yang lumayan ngebantu rutinitas harian."

def parse_time_str(t_str: str) -> int:
    t_clean = t_str.strip().replace(".", ":")
    if t_clean in ["24:00", "24.00", "00:00"]:
        return 23 * 60 + 59
    m = re.match(r"^(\d{1,2}):(\d{1,2})", t_clean)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return 4 * 60 + 30

def generate_slots(total_count, start_time_str="04:30", end_time_str="23:59"):
    if total_count <= 0:
        return []
    if total_count == 1:
        return ["12:00"]
    start_m = parse_time_str(start_time_str)
    end_m = parse_time_str(end_time_str)
    if end_m <= start_m:
        end_m = 23 * 60 + 59
    step = (end_m - start_m) / (total_count - 1)
    slots = []
    for i in range(total_count):
        curr_m = 5 * round(int(round(start_m + i * step)) / 5)
        if curr_m >= 24 * 60:
            curr_m = 23 * 60 + 55
        slots.append(f"{curr_m // 60:02d}:{curr_m % 60:02d}")
    return slots

def arrange_post_types_3way(num_viral: int, num_text: int, num_video: int) -> list:
    total = num_viral + num_text + num_video
    if total == 0:
        return []
    buckets = [["viral"] * num_viral, ["video"] * num_video, ["text"] * num_text]
    res = []
    while any(buckets):
        for b in buckets:
            if b:
                res.append(b.pop(0))
    return res[:total]

def prepare_media_for_post(media_raw: str, duplicate_single_video: bool = True) -> str:
    if not media_raw:
        return ""
    parts = [p.strip() for p in str(media_raw).split(",") if p.strip()]
    if len(parts) == 1 and duplicate_single_video:
        single = parts[0]
        is_video = any(single.lower().endswith(ext) for ext in [".mp4", ".mov", ".m4v"]) or "/video/upload/" in single
        if is_video:
            return f"{single}, {single}"
    return ", ".join(parts)

# ==========================================
# 🚀 INISIALISASI DATA
# ==========================================
try:
    sh, ws_data, ws_prods, ws_cfg, ws_acc, df_data, df_prods, cfg_dict, df_acc = load_all_worksheets()
except Exception as e:
    st.error(f"Gagal menghubungkan ke Google Sheets: {e}")
    st.stop()

# Header Aplikasi
col_h1, col_h2 = st.columns([3, 1])
with col_h1:
    st.title("🚀 Threads Affiliate AI Command Center")
    st.caption("24/7 Autopilot • Closed-Loop Self Learning • Dynamic Reply CTA • Exploration vs Winning Product")
with col_h2:
    if st.button("🔄 Refresh Data Spreadsheet", use_container_width=True):
        st.cache_resource.clear()
        st.rerun()

# TAB UTAMA DASHBOARD
tab_analytics, tab_queue, tab_products, tab_hijack, tab_config, tab_accounts = st.tabs([
    "📊 Analisa Data",
    "📅 Jadwal & Antrean",
    "📦 Database Produk",
    "🎯 Hijack & Balasan",
    "⚙️ Pengaturan Autopilot",
    "🔑 Akun Threads"
])

# =======================================================
# 📊 TAB 1: ANALISA DATA & AI SELF-LEARNING
# =======================================================
with tab_analytics:
    st.header("📈 Analisa Engagement & AI Self-Learning")
    st.caption("Statistik riil dari Threads API yang dianalisis oleh AI untuk menentukan hook viral, produk winning, dan jam posting terbaik.")

    if not df_data.empty:
        df_an = df_data.copy()
        for col in ["views", "likes", "replies", "reposts"]:
            if col in df_an.columns:
                df_an[col] = pd.to_numeric(df_an[col].replace("", 0), errors="coerce").fillna(0).astype(int)

        df_posted = df_an[df_an["status"].str.upper() == "POSTED"].copy()

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Views", f"{df_posted['views'].sum():,}" if "views" in df_posted else "0")
        c2.metric("Total Likes", f"{df_posted['likes'].sum():,}" if "likes" in df_posted else "0")
        c3.metric("Total Replies", f"{df_posted['replies'].sum():,}" if "replies" in df_posted else "0")
        c4.metric("Total Reposts", f"{df_posted['reposts'].sum():,}" if "reposts" in df_posted else "0")
        c5.metric("Total Post Sukses", f"{len(df_posted):,}")

        st.divider()
        col_l, col_r = st.columns([1, 1])

        with col_l:
            st.subheader("🏆 5 Postingan Terbaik (Winning Copies)")
            st.caption("Gaya dan struktur hook yang otomatis dipelajari Gemini:")
            if "views" in df_posted.columns and not df_posted.empty:
                top_winning = df_posted.sort_values(by="views", ascending=False).head(5)
                for _, r_win in top_winning.iterrows():
                    with st.expander(f"👁️ {r_win['views']:,} Views | ❤️ {r_win.get('likes', 0)} Likes — {r_win.get('date', '')} {r_win.get('time', '')}"):
                        main_txt_show = r_win.get("main_post", r_win.get("text", ""))
                        st.markdown(f"**Teks Postingan Utama:**\n\n> {main_txt_show}")
                        st.markdown(f"**Balasan CTA:** `{r_win.get('reply_text', '')}`")
            else:
                st.info("Belum ada data views yang tercatat.")

        with col_r:
            st.subheader("🛍️ Winning Products (Paling Diminati)")
            st.caption("Akumulasi views tertinggi berdasarkan tautan produk:")
            link_col = "affiliate_link" if "affiliate_link" in df_posted.columns else ("link" if "link" in df_posted.columns else "")
            if link_col and not df_prods.empty:
                prod_ranks = df_posted.groupby(link_col)["views"].sum().reset_index()
                merged_p = pd.merge(df_prods, prod_ranks, left_on="affiliate_link", right_on=link_col, how="left").fillna(0)
                merged_p = merged_p.sort_values(by="views", ascending=False)
                st.dataframe(merged_p[["product_name", "views", "status", "affiliate_link"]], use_container_width=True, height=280)
            else:
                st.info("Data produk belum cukup untuk dianalisa.")

        st.divider()
        st.subheader("⏰ Jam Tayang Paling Efektif (Peak Hours)")
        if not df_posted.empty and "time" in df_posted.columns:
            df_posted["hour"] = df_posted["time"].apply(lambda t: str(t).split(":")[0] if ":" in str(t) else "00")
            hourly_avg = df_posted.groupby("hour")["views"].mean().reset_index()
            hourly_avg["Jam"] = hourly_avg["hour"].apply(lambda h: f"{int(h):02d}:00 WIB")
            st.bar_chart(hourly_avg.set_index("Jam")["views"], height=250)
    else:
        st.info("Belum ada baris postingan di lembar data.")

# =======================================================
# 📅 TAB 2: JADWAL & ANTREAN POSTINGAN
# =======================================================
with tab_queue:
    st.header("📅 Manajemen Antrean & Pembuatan Draf")

    with st.expander("✨ Buat Draf Otomatis untuk Hari Ini (Interactive AI Generator)", expanded=False):
        st.write("Jalankan pembuatan draf instan langsung dari dashboard. Algoritma akan menyeimbangkan produk winning dan memberi jatah eksplorasi tinggi ke produk baru.")
        col_gen1, col_gen2, col_gen3 = st.columns([1, 1, 1])
        tgl_draf = col_gen1.date_input("Pilih Tanggal Draf", value=datetime.now(TZ).date())
        acc_choices = ["-- Semua Akun (All Accounts) --"] + list(df_acc["name"].unique() if not df_acc.empty else [])
        pilih_acc = col_gen2.selectbox("Pilih Target Akun", acc_choices)
        btn_generate_now = col_gen3.button("⚡ Generate Draf Sekarang", use_container_width=True)

        if btn_generate_now:
            with st.spinner("AI sedang merancang hook dan CTA dinamis..."):
                tgl_str = tgl_draf.strftime("%Y-%m-%d")
                daily_v = int(cfg_dict.get("daily_viral_count", cfg_dict.get("count_viral", 0)))
                daily_t = int(cfg_dict.get("daily_text_count", cfg_dict.get("count_aff_text", 0)))
                daily_vid = int(cfg_dict.get("daily_video_count", cfg_dict.get("count_aff_media", 20)))
                total_k = daily_v + daily_t + daily_vid
                if total_k == 0:
                    total_k, daily_vid = 20, 20

                s_clock = cfg_dict.get("start_time", "04:30")
                e_clock = cfg_dict.get("end_time", "23:59")
                slots = generate_slots(total_k, s_clock, e_clock)
                types = arrange_post_types_3way(daily_v, daily_t, daily_vid)

                ready_p = [p for p in df_prods.to_dict("records") if str(p.get("status", "")).strip().upper() == "READY"]
                if not ready_p:
                    st.error("Tidak ada produk berstatus 'READY' di tab Produk!")
                else:
                    target_acc_list = list(df_acc["name"].unique()) if pilih_acc == "-- Semua Akun (All Accounts) --" else [pilih_acc]
                    
                    # AI Context
                    posted_recs = df_data[df_data["status"].str.upper() == "POSTED"] if not df_data.empty else pd.DataFrame()
                    winning_prompt_ctx = ""
                    winning_prod_map = {}
                    if not posted_recs.empty and "views" in posted_recs.columns:
                        top3 = posted_recs.sort_values(by="views", ascending=False).head(3)
                        copies = [r.get("text", "") for _, r in top3.iterrows() if r.get("views", 0) > 0]
                        if copies:
                            winning_prompt_ctx = "\n[CONTOH POSTINGAN DENGAN VIEWS TERTINGGI]:\n" + "\n---\n".join(copies)
                        winning_prod_map = posted_recs.groupby("affiliate_link")["views"].sum().to_dict()

                    def pick_prod_boost(prod_list):
                        weights = []
                        for p in prod_list:
                            vw = winning_prod_map.get(p.get("affiliate_link", ""), None)
                            if vw is None:
                                weights.append(3.5) # Exploration Boost
                            elif vw == 0:
                                weights.append(1.2)
                            else:
                                weights.append(1.0 + min(vw / 120.0, 6.0))
                        return random.choices(prod_list, weights=weights, k=1)[0]

                    new_appended = 0
                    for ac_n in target_acc_list:
                        for s_tm, p_tp in zip(slots, types):
                            vb = random.choice(THREADS_VIBES)
                            if p_tp == "viral":
                                pr = f"Tulis 1 postingan Threads viral santai tentang: '{random.choice(VIRAL_OBSERVATIONS)}'. Vibe: {vb}. Maks 220 char tanpa kutip."
                                txt = call_gemini(pr)
                                ws_data.append_row([tgl_str, s_tm, ac_n, sanitize_threads_text(txt), "", "", "", "PENDING", "", "", "", ""])
                            elif p_tp == "video":
                                p_cur = pick_prod_boost([p for p in ready_p if str(p.get("media_url", "")).strip()] or ready_p)
                                pr = (
                                    f"Tulis pengantar video produk Threads:\nProduk: {p_cur['product_name']}\nHighlight: {p_cur.get('highlight','')}\n"
                                    f"Vibe: {vb}\n{winning_prompt_ctx}\n"
                                    f"Aturan: Sambungkan ke problem nyata, penonton sadar ini dijual murah di Shopee, jgn taruh link di post utama. Maks 290 char.\n"
                                    f"CTA Reply: Kalimat sangat singkat pemicu klik kontekstual (anti-zonk/keheranan harga murah), maks 110 char.\n"
                                    f"FORMAT WAJIB:\n[Teks Utama]\n---REPLY_CTA---\n[Teks CTA Balasan]"
                                )
                                out_g = call_gemini(pr)
                                if "---REPLY_CTA---" in out_g:
                                    m_tx, c_tx = out_g.split("---REPLY_CTA---", 1)
                                else:
                                    m_tx, c_tx = out_g, random.choice(FALLBACK_CTA_STARTERS)
                                rep_fl = f"{c_tx.strip()}\n{p_cur['affiliate_link']}"
                                m_fmt = prepare_media_for_post(str(p_cur.get("media_url", "")).strip(), True)
                                ws_data.append_row([tgl_str, s_tm, ac_n, sanitize_threads_text(m_tx), m_fmt, sanitize_threads_text(rep_fl), p_cur['affiliate_link'], "PENDING", "", "", "", ""])
                            else:
                                p_cur = pick_prod_boost(ready_p)
                                pr = (
                                    f"Tulis postingan teks Threads tentang produk:\nProduk: {p_cur['product_name']}\nHighlight: {p_cur.get('highlight','')}\n"
                                    f"Vibe: {vb}\n{winning_prompt_ctx}\n"
                                    f"FORMAT WAJIB:\n[Teks Utama]\n---REPLY_CTA---\n[Teks CTA Balasan]"
                                )
                                out_g = call_gemini(pr)
                                if "---REPLY_CTA---" in out_g:
                                    m_tx, c_tx = out_g.split("---REPLY_CTA---", 1)
                                else:
                                    m_tx, c_tx = out_g, random.choice(FALLBACK_CTA_STARTERS)
                                rep_fl = f"{c_tx.strip()}\n{p_cur['affiliate_link']}"
                                ws_data.append_row([tgl_str, s_tm, ac_n, sanitize_threads_text(m_tx), "", sanitize_threads_text(rep_fl), p_cur['affiliate_link'], "PENDING", "", "", "", ""])
                            new_appended += 1

                    st.success(f"Berhasil membuat {new_appended} draf baru untuk tanggal {tgl_str}!")
                    st.cache_resource.clear()
                    st.rerun()

    # Tabel Filter & Kontrol Antrean
    st.subheader("📋 Daftar Antrean Postingan")
    if not df_data.empty:
        col_fl1, col_fl2, col_fl3 = st.columns([1, 1, 2])
        opt_statuses = list(df_data["status"].str.upper().unique())
        f_stat = col_fl1.multiselect("Status", opt_statuses, default=opt_statuses)
        opt_dates = list(df_data["date"].unique())
        f_date = col_fl2.multiselect("Tanggal", opt_dates, default=opt_dates[-3:] if len(opt_dates) >= 3 else opt_dates)

        filtered_queue = df_data[df_data["status"].str.upper().isin(f_stat) & df_data["date"].isin(f_date)]
        st.dataframe(filtered_queue, use_container_width=True, height=400)
    else:
        st.info("Lembar data antrean masih kosong.")

# =======================================================
# 📦 TAB 3: DATABASE PRODUK
# =======================================================
with tab_products:
    st.header("📦 Katalog Produk Affiliate")
    st.write("Produk baru yang ditambahkan di sini otomatis mendapatkan **Exploration Boost** agar langsung diuji coba oleh AI.")

    with st.expander("➕ Tambah Produk Baru", expanded=True):
        with st.form("form_add_p", clear_on_submit=True):
            p_name = st.text_input("Nama Produk *", placeholder="Contoh: Alat Cungkil Pembersih Kuku Medis Anti-Cantengan")
            p_cat = st.text_input("Kategori", placeholder="Beauty / Home Living / Gadget")
            p_high = st.text_area("Highlight / Manfaat Solutif *", placeholder="Baja medis antikarat steril, lengkungan presisi, bersihin kotoran dan cantengan tanpa rasa sakit.")
            p_link = st.text_input("Link Shopee Affiliate *", placeholder="https://s.shopee.co.id/...")
            p_media = st.text_area("Media URL (Link Video MP4 / Cloudinary)", placeholder="https://res.cloudinary.com/.../video.mp4")
            p_stat = st.selectbox("Status", ["READY", "DRAFT"])
            btn_save_p = st.form_submit_button("Simpan Produk ke Spreadsheet")

            if btn_save_p:
                if p_name and p_link:
                    ws_prods.append_row([p_name, p_cat, p_high, p_link, p_media, p_stat])
                    st.success(f"Produk '{p_name}' berhasil ditambahkan dengan status {p_stat}!")
                    st.cache_resource.clear()
                    st.rerun()
                else:
                    st.error("Nama Produk dan Link Shopee Affiliate wajib diisi!")

    st.subheader("Daftar Produk Aktif")
    st.dataframe(df_prods, use_container_width=True, height=350)

# =======================================================
# 🎯 TAB 4: HIJACK & BALASAN
# =======================================================
with tab_hijack:
    st.header("🎯 Post Hijacking & Balasan Utas Viral")
    st.write("Suntikkan draf promosi atau komentar affiliate ke Threads akun orang lain yang sedang viral.")

    with st.form("form_hijack"):
        hj_acc = st.selectbox("Akun Pengirim", list(df_acc["name"].unique() if not df_acc.empty else []))
        hj_target_id = st.text_input("Target Threads Post ID", placeholder="Contoh: 181498172635412")
        hj_text = st.text_area("Teks Komentar Utama", placeholder="Ikutan nimbrung tapi nyambung sama topik viralnya...")
        hj_reply = st.text_area("Balasan CTA Shopee", placeholder="Lapak aslinya aku taro sini biar gampang:\nhttps://s.shopee.co.id/...")
        btn_submit_hj = st.form_submit_button("Jadwalkan Hijack ke Antrean")

        if btn_submit_hj:
            if hj_target_id and hj_text:
                now_str = datetime.now(TZ).strftime("%Y-%m-%d")
                time_str = datetime.now(TZ).strftime("%H:%M")
                ws_data.append_row([now_str, time_str, hj_acc, sanitize_threads_text(hj_text), "", sanitize_threads_text(hj_reply), "", "PENDING", "", "", "", hj_target_id])
                st.success("Target Hijack berhasil masuk ke jadwal antrean!")
                st.cache_resource.clear()
                st.rerun()
            else:
                st.error("Target Post ID dan Teks Komentar wajib diisi!")

# =======================================================
# ⚙️ TAB 5: PENGATURAN AUTOPILOT (DIPERBAIKI S/D 50 POST)
# =======================================================
with tab_config:
    st.header("⚙️ Pengaturan Jadwal & Porsi Konten")
    st.caption("Konfigurasi kapasitas harian hingga 50 postingan, rentang jam operasional 04:30 – 23:59, dan gaya tulisan AI.")

    # Parsing nilai config lama dari spreadsheet dengan aman
    cur_viral = int(cfg_dict.get("daily_viral_count", cfg_dict.get("count_viral", 0)))
    cur_text = int(cfg_dict.get("daily_text_count", cfg_dict.get("count_aff_text", 0)))
    cur_video = int(cfg_dict.get("daily_video_count", cfg_dict.get("count_aff_media", 20)))

    with st.form("form_config_main"):
        st.subheader("⏰ Jam Operasional Autopilot")
        c_tm1, c_tm2 = st.columns(2)
        start_time_in = c_tm1.text_input("Jam Mulai (Start Time)", value=cfg_dict.get("start_time", "04:30"))
        end_time_in = c_tm2.text_input("Jam Berakhir (End Time)", value=cfg_dict.get("end_time", "23:59"))

        st.subheader("🎯 Porsi Konten Harian (Maksimal s/d 50 Post)")
        c_por1, c_por2, c_por3 = st.columns(3)
        # Batas angka dinaikkan ke 50 dengan min() untuk mencegah StreamlitValueAboveMaxError
        sel_viral = c_por1.number_input("🔥 Postingan Viral / Relatable", 0, 50, min(max(cur_viral, 0), 50))
        sel_text = c_por2.number_input("📝 Produk Teks Organik", 0, 50, min(max(cur_text, 0), 50))
        sel_video = c_por3.number_input("🎬 Produk Video / Gambar", 0, 50, min(max(cur_video, 0), 50))

        total_target_p = sel_viral + sel_text + sel_video
        st.info(f"Total Target Konten per Hari: **{total_target_p} Postingan** (Jeda rata-rata: ~{max(1, 1140 // max(1, total_target_p))} menit antarpostingan)")

        st.subheader("📅 Rentang Tanggal Aktif")
        c_dt1, c_dt2 = st.columns(2)
        start_dt_in = c_dt1.text_input("Tanggal Mulai (Start Datetime)", value=cfg_dict.get("start_datetime", "2026-01-01 04:30"))
        end_dt_in = c_dt2.text_input("Tanggal Berakhir (End Datetime)", value=cfg_dict.get("end_datetime", "2026-12-31 23:59"))

        st.subheader("🤖 Personalisasi AI & Balasan")
        c_ai1, c_ai2 = st.columns(2)
        target_acc_opt = ["-- Semua Akun (All Accounts) --"] + list(df_acc["name"].unique() if not df_acc.empty else [])
        cur_acc_sel = cfg_dict.get("target_autopilot_account", "-- Semua Akun (All Accounts) --")
        sel_acc_cfg = c_ai1.selectbox("Target Akun", target_acc_opt, index=target_acc_opt.index(cur_acc_sel) if cur_acc_sel in target_acc_opt else 0)

        ai_style_opts = [
            "Serahkan ke AI (Smart Adaptive / Acak Tiap Post)",
            "Santai & Sarkas (Gaya Gen Z / Netizen Santai)",
            "Review Jujur Tanpa Filter (Fokus Masalah & Solusi)",
            "Aesthetic & Mindful (Ruang Tenang & Tertata)"
        ]
        cur_style = cfg_dict.get("ai_style", ai_style_opts[0])
        sel_ai_style = c_ai2.selectbox("Gaya Bahasa AI", ai_style_opts, index=ai_style_opts.index(cur_style) if cur_style in ai_style_opts else 0)

        btn_save_config = st.form_submit_button("Simpan Pengaturan ke Spreadsheet")

        if btn_save_config:
            new_configs = {
                "daily_viral_count": str(sel_viral),
                "daily_text_count": str(sel_text),
                "daily_video_count": str(sel_video),
                "count_viral": str(sel_viral),
                "count_aff_text": str(sel_text),
                "count_aff_media": str(sel_video),
                "start_time": start_time_in,
                "end_time": end_time_in,
                "start_datetime": start_dt_in,
                "end_datetime": end_dt_in,
                "target_autopilot_account": sel_acc_cfg,
                "ai_style": sel_ai_style
            }

            rows_cfg = ws_cfg.get_all_values()
            keys_list = [r[0].strip() for r in rows_cfg if r]

            for k, val in new_configs.items():
                if k in keys_list:
                    idx = keys_list.index(k) + 1
                    ws_cfg.update_cell(idx, 2, val)
                else:
                    ws_cfg.append_row([k, val])

            st.success("Pengaturan berhasil disimpan! Jadwal dan batas baru telah disinkronkan.")
            st.cache_resource.clear()
            st.rerun()

# =======================================================
# 🔑 TAB 6: AKUN THREADS
# =======================================================
with tab_accounts:
    st.header("🔑 Akun Threads Terdaftar")
    st.write("Pastikan access token setiap akun valid dan aktif agar publikasi dan penarikan analitik Meta API berjalan lancar.")

    with st.expander("➕ Hubungkan Akun Baru", expanded=False):
        with st.form("form_add_acc"):
            acc_name = st.text_input("Username Akun (tanpa @)", placeholder="contoh: arkaisha.store")
            acc_uid = st.text_input("Threads User ID", placeholder="contoh: 17841400000000000")
            acc_tok = st.text_area("Access Token Threads")
            btn_add_acc = st.form_submit_button("Simpan Akun")

            if btn_add_acc:
                if acc_name and acc_uid and acc_tok:
                    ws_acc.append_row([acc_name, acc_uid, acc_tok])
                    st.success(f"Akun @{acc_name} berhasil ditambahkan!")
                    st.cache_resource.clear()
                    st.rerun()
                else:
                    st.error("Semua kolom akun wajib diisi!")

    st.subheader("Daftar Akun Terhubung")
    st.dataframe(df_acc, use_container_width=True)
