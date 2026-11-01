import os
import re
import json
import base64
from datetime import datetime, time as dtime, date
import pytz
import pandas as pd
import requests
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Threads Autopilot & AI Self-Learning Hub",
    page_icon="🚀",
    layout="wide"
)

TZ = pytz.timezone("Asia/Jakarta")

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
        st.error("GCP_CREDS_BASE64 belum disetel di Secrets atau environment.")
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

def load_all_data():
    client = get_sheets_client()
    sh = client.open_by_key(SPREADSHEET_ID)

    # Worksheet data
    ws_data = sh.worksheet("data")
    data_rows = ws_data.get_all_values()
    df_data = pd.DataFrame(data_rows[1:], columns=data_rows[0]) if len(data_rows) > 1 else pd.DataFrame()

    # Worksheet Products
    ws_prods = sh.worksheet("Products")
    prod_rows = ws_prods.get_all_records()
    df_prods = pd.DataFrame(prod_rows)

    # Worksheet Config
    ws_cfg = sh.worksheet("Config")
    cfg_rows = ws_cfg.get_all_values()
    cfg_dict = {r[0].strip(): r[1].strip() for r in cfg_rows if len(r) >= 2 and r[0].strip()}

    # Worksheet Accounts
    ws_acc = sh.worksheet("Accounts")
    acc_rows = ws_acc.get_all_records()
    df_acc = pd.DataFrame(acc_rows)

    return sh, df_data, df_prods, cfg_dict, df_acc

st.title("🚀 Threads Affiliate AI Command Center")
st.caption("24/7 Autopilot • AI Self-Learning • Dynamic Reply CTA • Exploration vs Winning Product")

try:
    sh, df_data, df_prods, cfg_dict, df_acc = load_all_data()
except Exception as e:
    st.error(f"Gagal memuat database Google Sheets: {e}")
    st.stop()

tab_analytics, tab_products, tab_queue, tab_config, tab_accounts = st.tabs([
    "📊 Analisa & AI Self-Learning",
    "📦 Database Produk",
    "📅 Antrean Posting",
    "⚙️ Pengaturan Autopilot",
    "🔑 Akun Threads"
])

# ==========================================
# 📊 TAB 1: ANALISA & AI SELF-LEARNING
# ==========================================
with tab_analytics:
    st.header("📈 Kinerja & Analisis Engagement Threads")
    st.write("Data di bawah diperbarui secara otomatis dari Threads API untuk mengoptimalkan postingan berikutnya.")

    if not df_data.empty and "views" in df_data.columns:
        # Konversi angka metrik
        for col in ["views", "likes", "replies", "reposts"]:
            if col in df_data.columns:
                df_data[col] = pd.to_numeric(df_data[col].replace("", 0), errors="coerce").fillna(0).astype(int)

        posted_df = df_data[df_data["status"].str.upper() == "POSTED"].copy()

        # Metrik Ringkasan Utama
        c1, c2, c3, c4, c5 = st.columns(5)
        total_views = posted_df["views"].sum() if "views" in posted_df else 0
        total_likes = posted_df["likes"].sum() if "likes" in posted_df else 0
        total_replies = posted_df["replies"].sum() if "replies" in posted_df else 0
        total_reposts = posted_df["reposts"].sum() if "reposts" in posted_df else 0
        total_posts = len(posted_df)

        c1.metric("Total Views", f"{total_views:,}")
        c2.metric("Total Likes", f"{total_likes:,}")
        c3.metric("Total Balasan", f"{total_replies:,}")
        c4.metric("Total Repost", f"{total_reposts:,}")
        c5.metric("Total Post Sukses", f"{total_posts:,}")

        st.divider()

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.subheader("🏆 5 Postingan dengan Views Tertinggi (Winning Copies)")
            st.caption("Pola kalimat dan hook dari draf ini otomatis dipelajari Gemini untuk postingan baru.")
            top_posts = posted_df.sort_values(by="views", ascending=False).head(5)
            if not top_posts.empty and top_posts["views"].max() > 0:
                for idx, row in top_posts.iterrows():
                    with st.expander(f"👁️ {row['views']:,} Views | ❤️ {row.get('likes', 0)} Likes — {row.get('date', '')} {row.get('time', '')}"):
                        st.markdown(f"**Teks Postingan Utama:**\n\n> {row.get('text', '')}")
                        st.markdown(f"**Balasan CTA:** `{row.get('reply_text', '')}`")
            else:
                st.info("Belum ada postingan dengan data views lebih dari 0.")

        with col_right:
            st.subheader("🛍️ Winning Products (Paling Diminati)")
            st.caption("Produk yang mendapatkan akumulasi views tertinggi di linimasa.")
            if "affiliate_link" in posted_df.columns and not df_prods.empty:
                prod_stats = posted_df.groupby("affiliate_link")["views"].sum().reset_index()
                merged_prods = pd.merge(df_prods, prod_stats, on="affiliate_link", how="left").fillna(0)
                merged_prods = merged_prods.sort_values(by="views", ascending=False)
                st.dataframe(
                    merged_prods[["product_name", "views", "status", "affiliate_link"]],
                    use_container_width=True,
                    height=280
                )
            else:
                st.info("Data produk belum cukup untuk dianalisa.")

        st.divider()

        st.subheader("⏰ Analisis Jam Tayang Terbaik (Peak Hours)")
        st.caption("Rata-rata views per jam. AI memprioritaskan format video pada jam-jam paling ramai.")
        if not posted_df.empty:
            posted_df["hour"] = posted_df["time"].apply(lambda x: str(x).split(":")[0] if ":" in str(x) else "00")
            hour_summary = posted_df.groupby("hour")["views"].mean().reset_index()
            hour_summary["hour_label"] = hour_summary["hour"].apply(lambda h: f"{int(h):02d}:00 WIB")
            st.bar_chart(hour_summary.set_index("hour_label")["views"], height=250)

    else:
        st.info("Belum ada data analitik. Pastikan kolom 'views', 'likes', 'replies', 'reposts' sudah ada di tab data spreadsheet.")

# ==========================================
# 📦 TAB 2: DATABASE PRODUK
# ==========================================
with tab_products:
    st.header("📦 Tambah & Kelola Produk")
    st.write("Upload produk baru setiap hari di sini. AI akan otomatis memberikan **Exploration Boost** agar produk baru langsung diuji di jadwal terdekat.")

    with st.expander("➕ Tambah Produk Baru", expanded=False):
        with st.form("form_add_product", clear_on_submit=True):
            p_name = st.text_input("Nama Produk", placeholder="Contoh: Alat Cungkil Pembersih Kuku & Cantengan")
            p_cat = st.text_input("Kategori", placeholder="Beauty / Household / Gadget")
            p_highlight = st.text_area("Highlight / Manfaat / Problem Solved", placeholder="Ujung lengkung presisi, baja tahan karat steril, ngilangin nyeri cantengan tanpa perlu ke salon.")
            p_link = st.text_input("Link Shopee Affiliate", placeholder="https://s.shopee.co.id/...")
            p_media = st.text_area("Media URL (Video .mp4 / Gambar)", placeholder="https://res.cloudinary.com/.../video.mp4")
            p_status = st.selectbox("Status Awal", ["READY", "DRAFT"])
            btn_add = st.form_submit_button("Simpan Produk ke Database")

            if btn_add:
                if p_name and p_link:
                    ws_p = sh.worksheet("Products")
                    ws_p.append_row([p_name, p_cat, p_highlight, p_link, p_media, p_status])
                    st.success(f"Produk '{p_name}' berhasil ditambahkan dengan status {p_status}!")
                    st.rerun()
                else:
                    st.error("Nama Produk dan Link Affiliate wajib diisi!")

    st.subheader("Daftar Produk di Spreadsheet")
    st.dataframe(df_prods, use_container_width=True, height=350)

# ==========================================
# 📅 TAB 3: ANTREAN JADWAL POSTING
# ==========================================
with tab_queue:
    st.header("📅 Antrean Konten Harian")
    st.write("Daftar antrean postingan otomatis yang dieksekusi oleh GitHub Actions.")

    if not df_data.empty:
        status_filter = st.multiselect("Filter Status", ["PENDING", "POSTED", "ERROR"], default=["PENDING", "POSTED", "ERROR"])
        filtered_df = df_data[df_data["status"].str.upper().isin(status_filter)]
        st.dataframe(filtered_df, use_container_width=True, height=450)
    else:
        st.info("Tab data saat ini masih kosong.")

# ==========================================
# ⚙️ TAB 4: PENGATURAN AUTOPILOT
# ==========================================
with tab_config:
    st.header("⚙️ Konfigurasi Sistem Autopilot")
    st.write("Atur target postingan harian (hingga 50 post), jam operasional, dan parameter AI.")

    # Parsing nilai lama dari spreadsheet
    cur_viral = int(cfg_dict.get("daily_viral_count", cfg_dict.get("count_viral", 0)))
    cur_text = int(cfg_dict.get("daily_text_count", cfg_dict.get("count_aff_text", 0)))
    cur_video = int(cfg_dict.get("daily_video_count", cfg_dict.get("count_aff_media", 20)))

    with st.form("form_config"):
        st.subheader("⏰ Jam Operasional Autopilot")
        c_time1, c_time2 = st.columns(2)
        start_clock_str = c_time1.text_input("Jam Mulai (Format HH:MM)", value=cfg_dict.get("start_time", "04:30"))
        end_clock_str = c_time2.text_input("Jam Berakhir (Format HH:MM)", value=cfg_dict.get("end_time", "23:59"))

        st.subheader("🎯 Target Porsi Konten Harian (Maksimal 50 Post)")
        c_p1, c_p2, c_p3 = st.columns(3)
        # number_input diatur maksimal 50
        in_viral = c_p1.number_input("🔥 Postingan Viral / Curhat", 0, 50, min(cur_viral, 50))
        in_text = c_p2.number_input("📝 Produk Teks Organik", 0, 50, min(cur_text, 50))
        in_video = c_p3.number_input("🎬 Produk Video (Disarankan)", 0, 50, min(cur_video, 50))

        total_target = in_viral + in_text + in_video
        st.info(f"Total Target Konten per Hari: **{total_target} Postingan** (Interval rata-rata: ~{max(1, 1140 // max(1, total_target))} menit per post)")

        st.subheader("📅 Rentang Tanggal Aktif")
        c_d1, c_d2 = st.columns(2)
        in_start_date = c_d1.text_input("Tanggal Mulai", value=cfg_dict.get("start_datetime", "2026-01-01 04:30"))
        in_end_date = c_d2.text_input("Tanggal Berakhir", value=cfg_dict.get("end_datetime", "2026-12-31 23:59"))

        btn_save_cfg = st.form_submit_button("Simpan Pengaturan ke Spreadsheet")

        if btn_save_cfg:
            ws_cfg = sh.worksheet("Config")
            # Update key-value config
            settings_map = {
                "daily_viral_count": str(in_viral),
                "daily_text_count": str(in_text),
                "daily_video_count": str(in_video),
                "count_viral": str(in_viral),
                "count_aff_text": str(in_text),
                "count_aff_media": str(in_video),
                "start_time": start_clock_str,
                "end_time": end_clock_str,
                "start_datetime": in_start_date,
                "end_datetime": in_end_date
            }

            rows_cfg = ws_cfg.get_all_values()
            existing_keys = [r[0].strip() for r in rows_cfg if r]

            for k, v in settings_map.items():
                if k in existing_keys:
                    row_idx = existing_keys.index(k) + 1
                    ws_cfg.update_cell(row_idx, 2, v)
                else:
                    ws_cfg.append_row([k, v])

            st.success("Konfigurasi berhasil disimpan! Jadwal baru akan otomatis berlaku pada eksekusi berikutnya.")
            st.rerun()

# ==========================================
# 🔑 TAB 5: AKUN THREADS
# ==========================================
with tab_accounts:
    st.header("🔑 Akun Threads Terdaftar")
    st.write("Pastikan token akun tetap aktif agar publikasi dan analitik metrik berjalan lancar.")
    st.dataframe(df_acc, use_container_width=True)
