import os
import re
import json
import base64
import random
import time as time_lib
from datetime import datetime, time, date, timedelta
import pytz
import requests
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="Threads Marketing Dashboard",
    page_icon="🧵",
    layout="wide"
)

TZ = pytz.timezone("Asia/Jakarta")

# --- AMBIL KREDENSIAL (AMAN DARI CRASH SECRETS / ENV) ---
def get_secret(key, default=""):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)

SPREADSHEET_ID = get_secret("SPREADSHEET_ID", "12HI63liR64ugPz8IHQHy2gAhOOzSDMt0D0-YHO5x08E")
GCP_CREDS_BASE64 = get_secret("GCP_CREDS_BASE64")
AI_API_KEY = get_secret("AI_API_KEY")

# --- MATRIKS PILAR TOPIK THREADS DINAMIS ---
TOPIC_PILLARS = {
    "DEBAT_SEPELE": [
        "perdebatan kebiasaan sepele sehari-hari yang bikin orang terbagi jadi dua kubu sengit",
        "etika makan atau nongkrong yang sering bikin salah paham tapi jarang dibahas terbuka",
        "kebiasaan chatting yang diam-diam bikin jengkel (misal: kirim voice note 5 menit atau cuma 'P')"
    ],
    "SOSIAL_DEWASA": [
        "realita pertemanan di usia 25 tahun ke atas dan susahnya mencocokkan jadwal nongkrong",
        "momen ketika energi sosial (social battery) habis total dan pengen langsung pulang",
        "seni menetapkan batasan ke orang lain (subtle cut-off) tanpa merasa bersalah"
    ],
    "DUNIA_KERJA": [
        "situasi rapat kantor berjam-jam yang sebenernya bisa selesai dalam satu baris email",
        "perasaan serba salah waktu libur/cuti tapi notifikasi grup kantor masih muncul",
        "dilema perfeksionis vs yang penting tugas kelar tepat waktu biar cepat pulang"
    ],
    "RUMAH_KOST": [
        "masalah sepele di rumah atau kamar kost yang sering diabaikan padahal bikin emosi tiap hari",
        "perjuangan menjaga kerapian meja kerja atau kamar saat lagi sibuk-sibuknya",
        "barang printilan rumah tangga yang baru disadari faedahnya setelah dicoba sendiri"
    ],
    "JALANAN_KOMUTER": [
        "drama transportasi umum, antrean KRL/MRT, atau macetnya jalanan kota",
        "tipe orang menyebalkan yang sering ditemui di tempat umum atau transportasi massal"
    ],
    "NOSTALGIA_POPKULTUR": [
        "kebiasaan anak zaman rental PS dulu yang sekarang udah gak relevan lagi buat anak sekarang",
        "perbedaan cara kita menikmati waktu luang zaman sekolah vs pas udah kerja"
    ]
}

# --- ATURAN GAYA BAHASA (ANTI BROSUR SALES) ---
PROMPT_RULES_CLEAN = """
DILARANG KERAS (BLACKLIST TOPIK & KATA):
1. JANGAN PERNAH bahas: gaji, tanggal tua, bokek, reksadana, tabungan, investasi finansial, bayar kos, biaya hidup, atau hitung-hitungan uang.
2. JANGAN PERNAH pakai format tanya-jawab brosur iklan (Contoh terlarang: 'Pusing dengan X? Y solusinya!', 'Lagi butuh X?').
3. DILARANG pakai kata klise sales: 'solusinya', 'cukup dengan...', 'dijamin', 'hadir untuk Anda', 'yuk buruan'.

PANDUAN STRUKTUR & GAYA HOOK 1-3 DETIK:
- Baris pertama WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 EMOJI relevan yang berfungsi sebagai rem jempol (stop scrolling) penonton.
- Baris berikutnya gunakan sudut pandang orang pertama ('aku', 'suami', 'mertua', 'roommate', 'jujur baru sadar').
- Tulis mengalir, curhat nyata, ada emosi/gregetan, celetukan santai khas obrolan linimasa Threads Indonesia.
- Dilarang pakai hashtag (#), dilarang pakai tanda kutip dua.
"""

# --- 15 MATRIKS HOOK EMOSIONAL & RELASIONAL MULTI-TRIGGER ---
VIRAL_HOOK_PATTERNS = [
    "Trigger Drama Relasi (Pasangan/Mertua): Awali baris pertama dengan dialog/reaksi pasangan atau mertua huruf kapital (misal: 'SUAMI: KAMU KALAU NYUCI KOK RIBET BANGET? 😭😂' atau 'MERTUA DATANG MENDADAK: KOK RUMAH BERSIH BANGET? 😭').",
    "Trigger Nyaris Malu (Social Anxiety): Awali baris pertama dengan momen horor/panik di tempat umum huruf kapital (misal: 'HAMPIR MALU DI RUANG MEETING KANTOR GARA-GARA BASKET 😭💀' atau 'MOMEN HOROR KUAH RENDANG TUMPAH KE KEMEJA PUTIH 😭😭').",
    "Trigger Otoritas/Orang Dalam: Awali baris pertama dengan ucapan terima kasih huruf kapital ke dokter/tukang servis/koki/ahli yang kasih bocoran (misal: 'MAKASIH MBAK DOKTER YANG UDAH KASI TAU INI 😭🙏' atau 'BOCORAN DARI TEMEN YANG ANAK ARSITEK INTERIOR ✨').",
    "Trigger Kaum Mager/Satset: Awali baris pertama dengan pengakuan malas huruf kapital tapi nemu jalan pintas (misal: 'SEBAGAI ORANG YANG PALING MALES NYIKAT KAMAR MANDI... 🤣' atau 'TIPE ORANG YANG MASAK MAUNYA 10 MENIT JADI DAN CUCIAN CUMA 1 BIJI 😂').",
    "Trigger Satisfying/Sensorik: Awali baris pertama dengan kepuasan visual/suara huruf kapital (misal: 'THERAPY TERBAIK MINGGU INI: LIAT AIR RENDAMAN JADI BUTEK COKLAT 🤤😭' atau 'BUNYI KLIK DARI BENDA INI BIKIN KECANDUAN NGERAPIIN MEJA ✨').",
    "Trigger Parno/Micro-Anxiety: Awali baris pertama dengan rasa cemas/jijik huruf kapital (misal: 'PARNO TIAP LIAT KECOA MUNCUL DARI BAWAH KITCHEN SET 😭' atau 'TRAUMA NEMU KELABANG DI DALEM SEPATU KERJA 😭😭').",
    "Trigger Bukan Boros Tapi Investasi: Awali baris pertama dengan penegasan huruf kapital membela diri dari fomo (misal: 'BUKAN FOMO, INI NAMANYA INVESTASI RUMAH TANGGA 🤣😭' atau 'INVESTASI 20 RIBU BIAR GAK DEBAT SAMA LEMARI TIAP PAGI 😂').",
    "Trigger Reverse Psychology: Awali baris pertama dengan melarang audiens membeli karena bikin kecanduan/over-rapi (misal: 'JANGAN PERNAH CO BARANG INI KALO GAK MAU KETAGIHAN 😭' atau 'BAHAYA BANGET PUNYA BENDA INI, BIKIN HAMPIR KESIANGAN NGANTOR 💀').",
    "Trigger Terlambat Sadar (Umur): Awali baris pertama dengan keheranan kenapa baru tahu barang ini sekarang (misal: 'UMUR 27 TAHUN BARU SADAR BENDA KECIL INI NYELAMATIN PUNGGUNG 😭' atau 'KENAPA BENDA INI GAK MASUK KURIKULUM WAKTU GUA MERANTAU 5 TAHUN LALU?? 😭').",
    "Trigger Skeptis Berujung Tobat: Awali baris pertama dengan mengira awalnya cuma gimik iklan huruf kapital (misal: 'KIRAIN CUMA GIMIK IKLAN LEBAY, TERNYATA EMANG SESAKTI ITU 😭' atau 'UDAH PASRAH SAMA WAJAN GOSONG, TERNYATA BENERAN BERES DALAM 3 MENIT 😭').",
    "Trigger Mewah Modal Murah: Awali baris pertama dengan kontras harga receh vs sensasi hotel/kafe huruf kapital (misal: 'MODAL 25 RIBU TAPI KAMAR MANDI SERASA TOILET HOTEL BINTANG LIMA ✨' atau 'CARA BIAR GAK HABIS 50 RIBU TIAP HARI BUAT KOPI LITERAN KAFE ☕').",
    "Trigger Tragedi Kamar Kos: Awali baris pertama dengan problem ruang sempit anak kos huruf kapital (misal: 'MUSUH TERBESAR ANAK KOS: KAMAR LEMBAB SAMPE TAS KULIT BERJAMUR 😭😭' atau 'KETIKA KAMAR KOS GAK ADA DAPUR TAPI MAU MAKAN ENAK TENGAH MALEM... 😂').",
    "Trigger Drama Anabul: Awali baris pertama dengan kelakuan kucing/hewan peliharaan huruf kapital (misal: 'POV: KETIKA RUMAH DIKUASAI KUCING OREN DAN SEMUA BAJU BERBULU 😭' atau 'MENYELAMATKAN SOFA DARI AMUKAN KUCING OREN 🤣🙏').",
    "Trigger Pet-Peeves Sepele: Awali baris pertama dengan gangguan sepele yang bikin naik darah huruf kapital (misal: 'SUARA PINTU BERDECIT TIAP MALAM YANG BIKIN JANTUNGAN RESMI BERAKHIR 😭' atau 'EMOSI TIAP CHARGER KENDUR PAS DITINGGAL TIDUR, PAGI BATERE 5% 💀').",
    "Trigger Callout Segmen + Hacks: Awali baris pertama dengan panggilan segmen audiens huruf kapital (misal: 'BUIBU MERAPAT ‼️' atau 'ANAK KOS/TRAVELER MERAPAT ‼️') lalu bandingkan cara ini dengan cara lama yang bikin rugi/hancur."
]

CLOSING_NARRATIVES = [
    "Btw banyak yang nanya di DM, ini link toko resmi tempat aku beli ya mumpung masih promo:",
    "Biar gak salah beli atau dapet yang zonk, aku taro link official store-nya di sini ya:",
    "Yang mau samaan atau sekadar cek review pembeli lainnya, langsung kepoin di sini:",
    "Spill link belinya di sini ya guys, kemarin pas aku cek lagi ada diskon lumayan:",
    "Daripada ribet nyari tokonya satu-satu, langsung meluncur ke toko resminya di sini:",
    "Kalo mau checkout mending sekarang sebelum kehabisan stok, link belinya di sini:",
    "Kemarin dapet harga flash sale di toko ini dan pengirimannya cepet, linknya:",
    "Biar dapet garansi resmi dan barang original, belinya lewat link ini ya:",
    "Buat yang minta spill racunnya, ini link toko terpercaya yang sering aku pake:",
    "Yang mau CO taro keranjang dulu aja, mumpung vouchernya masih aktif di sini:"
]

# --- STRATEGI MODEL 1: PENEMPATAN FLEKSIBEL (AWAL / TENGAH / AKHIR) & CTA LUWES ---
MODEL_1_POSITION_PROMPTS = [
    (
        "POSISI LINK: AWAL KALIMAT.\n"
        "Letakkan placeholder '[LINK_PRODUK]' di kalimat pembuka/awal cerita secara natural dan luwes. "
        "Contoh alur: 'Gara-gara iseng nyobain lapak ini [LINK_PRODUK], drama kamar mandi berlumut akhirnya kelar...' "
        "CTA harus mengalir santai menyatu dengan curhat, DILARANG pakai template kaku, panah emoji berlebihan, atau bahasa sales."
    ),
    (
        "POSISI LINK: TENGAH KALIMAT.\n"
        "Selipkan placeholder '[LINK_PRODUK]' di tengah-tengah cerita saat menyebutkan solusi, keunggulan, atau momen kepuasan pakai barangnya. "
        "Contoh alur: 'Ternyata rahasia wajan gak gampang gosong cuma pakai silikon ini [LINK_PRODUK], beneran nol drama pas cuci...' "
        "CTA harus luwes seperti celetukan ngobrol sama temen dekat, jangan terasa jualan."
    ),
    (
        "POSISI LINK: AKHIR KALIMAT.\n"
        "Letakkan placeholder '[LINK_PRODUK]' di akhir cerita dengan kalimat rekomendasi penutup yang santai dan relate. "
        "Contoh alur: '...daripada beli yang tiruan gampang patah, mending cek lapak aslinya di [LINK_PRODUK] mumpung lagi diskon.' "
        "DILARANG pakai kalimat klise sales seperti 'Belinya disini ya' atau 'Klik link di bawah'."
    )
]

def sanitize_threads_text(text: str, max_chars: int = 495) -> str:
    if not text:
        return ""
    t = str(text).strip()

    t = re.sub(r'^\s*\[\s*(?:Teks\s+)?(?:Utama|Balasan\s+CTA|CTA|Postingan|Main\s+Post|Reply\s+CTA)\s*\]\s*:?\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'^\s*(?:Teks\s+Utama|Teks\s+Balasan\s+CTA|Balasan\s+CTA|CTA\s+Reply|Postingan\s+Utama)\s*:\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'\[\s*(?:Teks\s+)?(?:Utama|Balasan\s+CTA|CTA|Postingan|Link)\s*\]', '', t, flags=re.IGNORECASE)
    t = t.replace("---REPLY_CTA---", "").strip()

    if len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'"))):
        t = t[1:-1].strip()

    t = re.sub(r'^\s*POV\s*:\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'keranjang\s+kuning(?:nya)?', 'link toko resminya', t, flags=re.IGNORECASE)
    t = re.sub(r'link\s+di\s+bio', 'link di bawah', t, flags=re.IGNORECASE)

    t = t.strip()
    if len(t) > max_chars:
        return t[:max_chars - 3].rstrip() + "..."
    return t

def format_model_1_text(raw_text: str, aff_link: str) -> str:
    """Menyematkan tautan affiliate ke posisi placeholder (awal/tengah/akhir) secara luwes."""
    pattern = r'\[\s*(?:LINK_PRODUK|LINK|LINK PRODUK)\s*\]'
    if re.search(pattern, raw_text, flags=re.IGNORECASE):
        raw_text = re.sub(pattern, aff_link, raw_text, flags=re.IGNORECASE)
    elif "[LINK_PRODUK]" in raw_text:
        raw_text = raw_text.replace("[LINK_PRODUK]", aff_link)

    clean_txt = sanitize_threads_text(raw_text)

    if aff_link not in clean_txt:
        clean_txt = f"{clean_txt}\n\nLapak aslinya di sini ya: {aff_link}"
        clean_txt = sanitize_threads_text(clean_txt)

    return clean_txt

def _safe_float(val) -> float:
    s = str(val).strip().replace(',', '')
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0

# ==============================================================================
# MODUL AI SELF-LEARNING & DECISION ENGINE (MODEL 1 VS MODEL 2)
# ==============================================================================
def extract_self_learning_patterns(data_items):
    """Mengekstrak pola copywriting terbaik dan produk dengan konversi tertinggi dari data Sheets."""
    if not data_items:
        return {"winning_copies": [], "winning_products": {}}

    posted_rows = []
    for r in data_items:
        if isinstance(r, dict):
            if str(r.get("status", "")).strip().upper() == "POSTED":
                v = _safe_float(r.get("views", 0))
                l = _safe_float(r.get("likes", 0))
                rep = _safe_float(r.get("replies", 0))
                repst = _safe_float(r.get("reposts", 0))
                score = v + (l * 5.0) + (rep * 8.0) + (repst * 10.0)
                posted_rows.append({
                    "text": str(r.get("main_text", r.get("text", ""))).strip(),
                    "aff_link": str(r.get("affiliate_link", r.get("link", ""))).strip(),
                    "score": score
                })
        elif isinstance(r, (list, tuple)):
            if len(r) >= 8 and str(r[7]).strip().upper() == "POSTED":
                v = _safe_float(r[12]) if len(r) > 12 else 0.0
                l = _safe_float(r[13]) if len(r) > 13 else 0.0
                rep = _safe_float(r[14]) if len(r) > 14 else 0.0
                repst = _safe_float(r[15]) if len(r) > 15 else 0.0
                score = v + (l * 5.0) + (rep * 8.0) + (repst * 10.0)
                posted_rows.append({
                    "text": str(r[3]).strip() if len(r) > 3 else "",
                    "aff_link": str(r[6]).strip() if len(r) > 6 else "",
                    "score": score
                })

    if not posted_rows:
        return {"winning_copies": [], "winning_products": {}}

    sorted_by_score = sorted(posted_rows, key=lambda x: x["score"], reverse=True)
    top_copies = [x["text"] for x in sorted_by_score[:3] if x["score"] > 0]

    product_scores = {}
    for x in posted_rows:
        link = x["aff_link"]
        if link:
            product_scores[link] = product_scores.get(link, 0.0) + x["score"]

    return {
        "winning_copies": top_copies,
        "winning_products": product_scores
    }

def calculate_model_engagement_ratio(data_items, acc_filter=None):
    """Menganalisis performa historis Model 1 vs Model 2 berdasarkan engagement riil."""
    m1_scores = []
    m2_scores = []

    for r in data_items:
        if isinstance(r, dict):
            if str(r.get("status", "")).strip().upper() != "POSTED":
                continue
            if acc_filter and str(r.get("account", r.get("name", ""))).strip() != str(acc_filter).strip():
                continue
            v = _safe_float(r.get("views", 0))
            l = _safe_float(r.get("likes", 0))
            rep = _safe_float(r.get("replies", 0))
            repst = _safe_float(r.get("reposts", 0))
            score = v + (l * 5.0) + (rep * 8.0) + (repst * 10.0)

            reply_val = str(r.get("reply_chain", r.get("reply", ""))).strip()
            if not reply_val or reply_val.lower() == "nan":
                m1_scores.append(score)
            else:
                m2_scores.append(score)
        elif isinstance(r, (list, tuple)):
            if len(r) >= 8 and str(r[7]).strip().upper() == "POSTED":
                if acc_filter and len(r) > 2 and str(r[2]).strip() != str(acc_filter).strip():
                    continue
                v = _safe_float(r[12]) if len(r) > 12 else 0.0
                l = _safe_float(r[13]) if len(r) > 13 else 0.0
                rep = _safe_float(r[14]) if len(r) > 14 else 0.0
                repst = _safe_float(r[15]) if len(r) > 15 else 0.0
                score = v + (l * 5.0) + (rep * 8.0) + (repst * 10.0)

                reply_val = str(r[5]).strip() if len(r) > 5 else ""
                if not reply_val or reply_val.lower() == "nan":
                    m1_scores.append(score)
                else:
                    m2_scores.append(score)

    if acc_filter and (len(m1_scores) + len(m2_scores)) < 3:
        return calculate_model_engagement_ratio(data_items, acc_filter=None)

    avg_m1 = sum(m1_scores) / len(m1_scores) if m1_scores else 0.0
    avg_m2 = sum(m2_scores) / len(m2_scores) if m2_scores else 0.0

    if avg_m1 == 0 and avg_m2 == 0:
        w_m1, w_m2 = 0.5, 0.5
    else:
        total = avg_m1 + avg_m2
        raw_m1 = (avg_m1 / total) if total > 0 else 0.5
        w_m1 = max(0.20, min(0.80, raw_m1))
        w_m2 = 1.0 - w_m1

    return {
        "avg_m1": avg_m1,
        "avg_m2": avg_m2,
        "weight_m1": w_m1,
        "weight_m2": w_m2
    }

def decide_post_model_by_ai(slot_time: str, model_weights: dict) -> bool:
    """Menentukan secara dinamis True = Model 1 (Direct), False = Model 2 (Reply)."""
    w1 = model_weights.get("weight_m1", 0.5)
    try:
        h = int(slot_time.split(":")[0])
        if h in [12, 13, 19, 20, 21]:
            w1 = max(0.15, w1 - 0.15)
        elif h in [7, 8, 15, 16, 22]:
            w1 = min(0.85, w1 + 0.15)
    except Exception:
        pass
    return random.random() < w1

def decide_post_model_for_account(acc_name: str, cfg_data: dict, slot_time: str, data_items: list, default_model_stats: dict) -> bool:
    """Menentukan format postingan per akun: Mode MANUAL (Persentase) atau AI_DYNAMIC."""
    mode_key = f"model_decision_mode_{acc_name}"
    mode = cfg_data.get(mode_key, cfg_data.get("model_decision_mode", "MANUAL")).strip().upper()

    if mode == "AI_DYNAMIC":
        acc_stats = calculate_model_engagement_ratio(data_items, acc_filter=acc_name)
        return decide_post_model_by_ai(slot_time, acc_stats)

    ratio_key = f"model_1_ratio_{acc_name}"
    try:
        m1_ratio = float(cfg_data.get(ratio_key, cfg_data.get("model_1_ratio", 30)))
    except Exception:
        m1_ratio = 30.0

    return (random.uniform(0, 100) < m1_ratio)

def extract_threads_media_id(input_str: str) -> str:
    cleaned = str(input_str).strip()
    if cleaned.isdigit():
        return cleaned
    m = re.search(r"(?:post|t)/([A-Za-z0-9_-]+)", cleaned)
    if not m:
        return cleaned
    shortcode = m.group(1)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    media_id = 0
    try:
        for char in shortcode:
            media_id = media_id * 64 + alphabet.index(char)
        return str(media_id)
    except Exception:
        return shortcode

# --- KONEKSI GOOGLE SHEETS ---
@st.cache_resource
def get_gspread_client():
    raw_creds = str(GCP_CREDS_BASE64).strip() if GCP_CREDS_BASE64 else ""
    if not raw_creds:
        return None
    try:
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
    except Exception as e:
        st.error(f"Gagal otentikasi Service Account: {e}")
        return None

def get_spreadsheet():
    client = get_gspread_client()
    if not client or not SPREADSHEET_ID:
        return None
    return client.open_by_key(SPREADSHEET_ID)

# --- CACHE DATA READING ---
@st.cache_data(ttl=60)
def load_all_sheets_data():
    client = get_gspread_client()
    if not client or not SPREADSHEET_ID:
        return {}, [], [], []

    sh_obj = client.open_by_key(SPREADSHEET_ID)

    cfg_data = {}
    try:
        cfg_rows = sh_obj.worksheet("Config").get_all_values()
        for r in cfg_rows:
            if len(r) >= 2 and r[0].strip():
                cfg_data[r[0].strip()] = r[1].strip()
    except Exception:
        pass

    try:
        prod_rows = sh_obj.worksheet("Products").get_all_records()
    except Exception:
        prod_rows = []

    try:
        acc_rows = sh_obj.worksheet("Accounts").get_all_records()
    except Exception:
        acc_rows = []

    try:
        data_rows = sh_obj.worksheet("data").get_all_records()
    except Exception:
        data_rows = []

    return cfg_data, prod_rows, acc_rows, data_rows

def parse_dt(s: str) -> datetime:
    cleaned = str(s).strip().replace("'", "")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})$", cleaned)
    if not m:
        raise ValueError(f"Format tidak valid: {s}")
    y, mo, d, h, mi = map(int, m.groups())
    return TZ.localize(datetime(y, mo, d, h, mi))

def generate_slots(total_count, start_time_str="04:30", end_time_str="23:45"):
    if total_count <= 0:
        return []
    if total_count == 1:
        return ["12:00"]
    h1, m1 = map(int, start_time_str.split(":"))
    h2, m2 = map(int, end_time_str.split(":"))
    start_minutes = h1 * 60 + m1
    end_minutes = h2 * 60 + m2
    if end_minutes <= start_minutes:
        end_minutes = 23 * 60 + 45
    step = (end_minutes - start_minutes) / (total_count - 1)
    slots = []
    for i in range(total_count):
        curr_m = 5 * round(int(round(start_minutes + i * step)) / 5)
        if curr_m >= 24 * 60:
            curr_m = 23 * 60 + 45
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

def get_random_dynamic_topic() -> tuple[str, str]:
    category = random.choice(list(TOPIC_PILLARS.keys()))
    sub_topic = random.choice(TOPIC_PILLARS[category])
    angles = [
        "Celetukan keheranan santai khas tongkrongan",
        "Pengakuan kebiasaan unik yang ternyata banyak dialami orang lain",
        "Opini pemantik yang memancing dua kubu warganet berkomentar sengit",
        "Keluhan relatable terhadap situasi tersebut tanpa nada menggurui"
    ]
    return sub_topic, random.choice(angles)

def pick_length_by_bias(bias: str) -> str:
    lengths = ["Pendek", "Sedang", "Panjang"]
    if "Dominan Pendek" in bias:
        weights = [0.60, 0.25, 0.15]
    elif "Dominan Panjang" in bias:
        weights = [0.15, 0.25, 0.60]
    elif "Dominan Sedang" in bias:
        weights = [0.20, 0.60, 0.20]
    else:
        weights = [0.33, 0.34, 0.33]
    return random.choices(lengths, weights=weights, k=1)[0]

def get_length_prompt_desc(length_opt: str) -> str:
    if "Pendek" in length_opt:
        return "Tulis sangat to-the-point dan ringkas (maksimal 100-140 karakter, 1-2 kalimat saja)."
    elif "Panjang" in length_opt:
        return "Tulis mengalir seperti curhat storytelling lengkap (sekitar 300-450 karakter)."
    else:
        return "Tulis dengan panjang sedang standar Threads (sekitar 180-260 karakter)."

def resolve_reply_count(reply_mode: str) -> int:
    if "1 - 3" in reply_mode:
        return random.randint(1, 3)
    elif "1 - 5" in reply_mode:
        return random.randint(1, 5)
    elif "2 - 4" in reply_mode:
        return random.randint(2, 4)
    m = re.search(r"\d+", str(reply_mode))
    if m:
        return max(1, int(m.group()))
    return 1

def resolve_style_desc(style_opt: str) -> str:
    if "Serahkan ke AI" in style_opt:
        pool = [
            "Curhat Santai & Relate (Bahasa Threads anak muda)",
            "Storytelling Pengalaman Pribadi (Masalah Emosi -> Solusi)",
            "Review Jujur & Solutif (Highlight keunggulan barang)",
            "Racun Belanja Belagu/Lucu (Antusias & bikin pengen punya)"
        ]
        return f"Gaya bahasa: {random.choice(pool)}"
    return f"Gaya bahasa: {style_opt}"

def update_config_keys(sh_obj, kv_pairs: dict):
    cfg_ws = sh_obj.worksheet("Config")
    all_vals = cfg_ws.get_all_values()
    existing_keys = {}
    for row_idx, r in enumerate(all_vals, start=1):
        if r and r[0].strip():
            existing_keys[r[0].strip()] = row_idx
    for k, v in kv_pairs.items():
        if k in existing_keys:
            cfg_ws.update_cell(existing_keys[k], 2, str(v))
        else:
            cfg_ws.append_row([k, str(v)])

# --- CALL GEMINI REST API (PRIORITAS PRO & SMART FALLBACK) ---
def call_gemini_core(prompt: str) -> tuple:
    key = str(AI_API_KEY).strip().replace("'", "").replace('"', "") if AI_API_KEY else ""
    if not key:
        raise Exception("API Key Gemini (AI_API_KEY) belum disetel!")

    target_models = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"]
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.85, "topP": 0.95, "maxOutputTokens": 800}
    }

    errors = []
    for m_name in target_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={key}"
        headers = {"Content-Type": "application/json"}
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            if r.status_code == 200:
                res = r.json()
                if "candidates" in res and res["candidates"]:
                    return res["candidates"][0]["content"]["parts"][0]["text"].strip(), f"v1beta/{m_name}"
            else:
                errors.append(f"{m_name} ({r.status_code})")
        except Exception as e:
            errors.append(f"{m_name} ({str(e)[:50]})")

    err_msg = " | ".join(errors[:2]) if errors else "Gagal menghubungi Gemini API."
    raise Exception(err_msg)

def call_gemini(prompt: str) -> str:
    text, _ = call_gemini_core(prompt)
    return text

def generate_affiliate_replies(prod_name: str, prod_hl: str, aff_link: str, reply_count: int) -> list:
    if reply_count <= 0 or not aff_link:
        return []

    try:
        prompt_closing = (
            f"Tulis 1 kalimat pengantar santai dan natural (maksimal 70 karakter) sebelum spill link toko resmi pembelian '{prod_name}'. "
            f"Contoh tema: info official store, voucher diskon toko, atau alasan checkout mumpung ready. "
            f"Tanpa hashtag, tanpa tanda kutip, dan JANGAN tulis link-nya."
        )
        closing_intro = call_gemini(prompt_closing).strip().strip('"').strip("'")
        if not closing_intro or len(closing_intro) > 100:
            closing_intro = random.choice(CLOSING_NARRATIVES)
    except Exception:
        closing_intro = random.choice(CLOSING_NARRATIVES)

    final_reply = f"{closing_intro}\n{aff_link}"

    if reply_count == 1:
        return [final_reply]

    intermediate_count = reply_count - 1
    prompt_intermediate = (
        f"Untuk postingan Threads tentang produk '{prod_name}' (Keunggulan: '{prod_hl}'). "
        f"Tulis persis {intermediate_count} tweet balasan pendek lanjutan yang menyambung secara bertahap (sebelum spill link). "
        f"Gaya santai, relate, jujur seperti curhat pengalaman pakai. Pisahkan setiap balasan dengan tanda '---'. "
        f"Maksimal 120 karakter per balasan. DILARANG pakai hashtag dan JANGAN sebutkan link."
    )
    try:
        raw_res = call_gemini(prompt_intermediate)
        parts = [p.strip() for p in raw_res.split("---") if p.strip()]
        replies = parts[:intermediate_count]
        while len(replies) < intermediate_count:
            replies.append("Worth it banget sih ini buat pemakaian jangka panjang.")
    except Exception:
        replies = ["Barang ini praktis banget buat kebutuhan sehari-hari." for _ in range(intermediate_count)]

    replies.append(final_reply)
    return replies

def check_threads_token(user_id: str, access_token: str) -> dict:
    url = f"https://graph.threads.net/v1.0/me?fields=id,username,threads_profile_picture_url&access_token={access_token}"
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except Exception as e:
        return {"error": {"message": str(e)}}

# --- TAMPILAN HEADER DASHBOARD ---
c_head1, c_head2 = st.columns([4, 1])
with c_head1:
    st.title("🧵 Threads Affiliate & Autopilot Dashboard")
    st.caption("Pusat kendali konten autopilot, manual & Thread Hijacking (Komentar Video di Postingan Viral).")
with c_head2:
    if st.button("🔄 Segarkan Data Sheets"):
        st.cache_data.clear()
        st.rerun()

# Load Data dari Cache
try:
    cfg_data, raw_prods, acc_records, all_data = load_all_sheets_data()
except Exception as e:
    if "429" in str(e):
        st.error("⏳ Google Sheets API terkena jeda kuota request. Tunggu 30-60 detik lalu klik '🔄 Segarkan Data Sheets'.")
    else:
        st.error(f"Gagal memuat data Google Sheets: {e}")
    st.stop()

# Tab Menu
tabs = st.tabs([
    "⚡ Kontrol Autopilot",
    "🎯 Hijack Thread Viral",
    "📦 Katalog Produk (50+ Items)",
    "✍️ Content Studio (Manual & AI)",
    "📋 Antrean & Riwayat",
    "⚙️ Akun Threads & Diagnostik",
    "📊 Analisa Data & AI"
])

# ==============================================================================
# TAB 1: KONTROL AUTOPILOT (DILENGKAPI MODEL 1 & 2 DENGAN AI SELF-LEARNING)
# ==============================================================================
with tabs[0]:
    st.subheader("Pengaturan Jadwal & Komposisi Harian Autopilot")
    st.write("Atur tanggal aktif, rasio harian (**Video**, **Teks**, **Viral**), dan **gaya penulisan AI**.")

    raw_start = cfg_data.get("start_datetime", "2026-01-01 04:30")
    raw_end = cfg_data.get("end_datetime", "2026-12-31 23:45")

    try:
        cur_viral_count = int(cfg_data.get("daily_viral_count", 0))
    except:
        cur_viral_count = 0

    try:
        cur_text_count = int(cfg_data.get("daily_text_count", 0))
    except:
        cur_text_count = 0

    try:
        cur_video_count = int(cfg_data.get("daily_video_count", 20))
    except:
        cur_video_count = 20

    cur_target_acc = cfg_data.get("target_autopilot_account", "-- Semua Akun (All Accounts) --")
    cur_reply_mode = cfg_data.get("reply_mode", "1 Balasan (Hanya Link)")
    cur_length_bias = cfg_data.get("length_bias", "Dominan Pendek (Lebih banyak ringkas)")
    cur_ai_style = cfg_data.get("ai_style", "Serahkan ke AI (Smart Adaptive / Acak Tiap Post)")

    now = datetime.now(TZ)
    try:
        cur_start = parse_dt(raw_start)
        cur_end = parse_dt(raw_end)
        is_active = (cur_start.date() <= now.date() <= cur_end.date())
    except Exception:
        is_active = False

    col_stat1, col_stat2 = st.columns(2)
    with col_stat1:
        if is_active:
            st.success(f"🟢 **STATUS: AUTOPILOT AKTIF**\n\nWaktu sekarang: `{now.strftime('%Y-%m-%d %H:%M:%S')} WIB`")
        else:
            st.warning(f"🔴 **STATUS: AUTOPILOT NON-AKTIF / DI LUAR JADWAL**\n\nWaktu sekarang: `{now.strftime('%Y-%m-%d %H:%M:%S')} WIB`")
    with col_stat2:
        total_daily = cur_viral_count + cur_text_count + cur_video_count
        st.info(
            f"**Konfigurasi Tersimpan Saat Ini:**\n"
            f"- Jadwal: `{raw_start} WIB` s/d `{raw_end} WIB`\n"
            f"- Kuota Harian: **{total_daily} Konten** ({cur_video_count} Video + {cur_text_count} Teks + {cur_viral_count} Viral)\n"
            f"- Target Akun: `{cur_target_acc}`"
        )

    st.divider()

    st.write("#### 🛠️ Sesuaikan Jadwal & Komposisi Harian")
    acc_names_all = [str(a["name"]).strip() for a in acc_records if str(a.get("name", "")).strip()]
    auto_acc_options = ["-- Semua Akun (All Accounts) --"] + acc_names_all

    col_ap_acc, _ = st.columns([2, 2])
    with col_ap_acc:
        def_acc_idx = auto_acc_options.index(cur_target_acc) if cur_target_acc in auto_acc_options else 0
        sel_auto_acc = st.selectbox("🎯 Target Akun Autopilot", auto_acc_options, index=def_acc_idx)

    col_d1, col_t1 = st.columns(2)
    with col_d1:
        try:
            def_start_date = parse_dt(raw_start).date()
        except:
            def_start_date = now.date()
        start_d = st.date_input("Tanggal Mulai (Start Date)", value=def_start_date)
    with col_t1:
        try:
            def_start_time = parse_dt(raw_start).time()
        except:
            def_start_time = time(4, 30)
        start_t = st.time_input("Jam Mulai (Start Time)", value=def_start_time)

    col_d2, col_t2 = st.columns(2)
    with col_d2:
        try:
            def_end_date = parse_dt(raw_end).date()
        except:
            def_end_date = now.date()
        end_d = st.date_input("Tanggal Berakhir (End Date)", value=def_end_date)
    with col_t2:
        try:
            def_end_time = parse_dt(raw_end).time()
        except:
            def_end_time = time(23, 45)
        end_t = st.time_input("Jam Berakhir (End Time)", value=def_end_time)

    st.write("##### 🎯 Porsi Konten Harian (Maksimal s/d 50 Post)")
    col_q1, col_q2, col_q3 = st.columns(3)
    with col_q1:
        sel_video = st.number_input("🎬 Produk Video / Gambar", 0, 50, min(max(cur_video_count, 0), 50))
    with col_q2:
        sel_text = st.number_input("📝 Produk Teks Saja", 0, 50, min(max(cur_text_count, 0), 50))
    with col_q3:
        sel_viral = st.number_input("🚀 Konten Viral Booster", 0, 50, min(max(cur_viral_count, 0), 50))

    auto_dup_video = st.checkbox("🎬 Trik Thumbnail: Jika produk hanya punya 1 video, kirim jadi 2 video (Carousel)", value=True)

    col_st1, col_st2 = st.columns(2)
    with col_st1:
        ai_style_options = [
            "Serahkan ke AI (Smart Adaptive / Acak Tiap Post)",
            "Curhat Santai & Relate (Bahasa Threads anak muda)",
            "Storytelling Pengalaman Pribadi (Masalah -> Solusi)",
            "Review Jujur & Solutif (Highlight keunggulan produk)",
            "Racun Belanja Shopee (Antusias & bikin pengen checkout)"
        ]
        def_style_idx = ai_style_options.index(cur_ai_style) if cur_ai_style in ai_style_options else 0
        sel_ai_style_ap = st.selectbox("🎨 Gaya Bahasa AI (Autopilot)", ai_style_options, index=def_style_idx)
    with col_st2:
        bias_options = [
            "Dominan Sedang (Lebih banyak standar)",
            "Dominan Pendek (Lebih banyak ringkas)",
            "Dominan Panjang (Lebih banyak storytelling)",
            "Acak Seimbang (Rata: Pendek, Sedang, Panjang)"
        ]
        def_bias_idx = bias_options.index(cur_length_bias) if cur_length_bias in bias_options else 0
        sel_bias_autopilot = st.selectbox("🎲 Pola Panjang Teks", bias_options, index=def_bias_idx)

    st.write("##### 💬 Format Rantai Balasan (Reply Chain - Khusus Model 2)")
    reply_mode_options = [
        "1 Balasan (Hanya Link)",
        "🎲 Acak (1 - 3 Balasan)",
        "🎲 Acak (1 - 5 Balasan)",
        "🎲 Acak (2 - 4 Balasan)",
        "2 Balasan (1 Cerita + Link)",
        "3 Balasan (2 Cerita + Link)"
    ]
    def_rep_idx = reply_mode_options.index(cur_reply_mode) if cur_reply_mode in reply_mode_options else 0
    sel_reply_mode_ap = st.selectbox("Pilih Format Balasan Utas:", reply_mode_options, index=def_rep_idx)

    total_plan = sel_video + sel_text + sel_viral
    preview_slots = generate_slots(total_plan, start_time_str=start_t.strftime("%H:%M"), end_time_str=end_t.strftime("%H:%M"))
    preview_types = arrange_post_types_3way(sel_viral, sel_text, sel_video)

    type_labels = {"viral": "Viral 🚀", "video": "Video 🎬", "text": "Teks 📝"}
    st.caption(f"💡 **Total:** {total_plan} post/hari ({sel_video} Video, {sel_text} Teks, {sel_viral} Viral).")
    slot_badges = [f"`{preview_slots[i]} ({type_labels.get(preview_types[i], 'Post')})`" for i in range(total_plan)]
    st.markdown("🕒 **Distribusi Jam:** " + " ➜ ".join(slot_badges))

    if st.button("💾 Simpan Pengaturan Autopilot", type="primary"):
        sh_obj = get_spreadsheet()
        if sh_obj:
            try:
                new_start_str = f"'{start_d.strftime('%Y-%m-%d')} {start_t.strftime('%H:%M')}"
                new_end_str = f"'{end_d.strftime('%Y-%m-%d')} {end_t.strftime('%H:%M')}"

                update_config_keys(sh_obj, {
                    "start_datetime": new_start_str,
                    "end_datetime": new_end_str,
                    "start_time": start_t.strftime("%H:%M"),
                    "end_time": end_t.strftime("%H:%M"),
                    "daily_viral_count": str(sel_viral),
                    "daily_text_count": str(sel_text),
                    "daily_video_count": str(sel_video),
                    "count_viral": str(sel_viral),
                    "count_aff_text": str(sel_text),
                    "count_aff_media": str(sel_video),
                    "target_autopilot_account": str(sel_auto_acc),
                    "reply_mode": str(sel_reply_mode_ap),
                    "length_bias": str(sel_bias_autopilot),
                    "ai_style": str(sel_ai_style_ap)
                })
                st.cache_data.clear()
                st.success("✅ Pengaturan autopilot tersimpan!")
                st.rerun()
            except Exception as e:
                st.error(f"Gagal menyimpan: {e}")

    # ==========================================================================
    # PENGATURAN KOMPOSISI MODEL 1 & 2 PER AKUN (BY PERCENTAGE / AI)
    # ==========================================================================
    st.divider()
    st.write("#### ⚖️ Pengaturan Komposisi Model Postingan per Akun (Model 1 vs Model 2)")
    st.caption("Tentukan format postingan per akun: Model 1 (Direct Link fleksibel di Post Utama) vs Model 2 (Link di Kolom Balasan) via persentase manual atau diserahkan ke AI.")

    acc_options_model = acc_names_all if acc_names_all else ["-- Belum ada akun --"]
    sel_acc_model = st.selectbox(
        "Pilih Akun Threads yang Ingin Diatur:",
        acc_options_model,
        key="sel_acc_model_setting"
    )

    if sel_acc_model and sel_acc_model != "-- Belum ada akun --":
        key_mode_acc = f"model_decision_mode_{sel_acc_model}"
        key_m1_acc = f"model_1_ratio_{sel_acc_model}"

        cur_acc_mode = cfg_data.get(key_mode_acc, cfg_data.get("model_decision_mode", "MANUAL")).upper()
        try:
            cur_acc_m1 = int(cfg_data.get(key_m1_acc, cfg_data.get("model_1_ratio", 30)))
        except Exception:
            cur_acc_m1 = 30

        choice_model_mode = st.radio(
            f"Metode Penentuan Model untuk {sel_acc_model}:",
            options=["MANUAL", "AI_DYNAMIC"],
            index=0 if cur_acc_mode == "MANUAL" else 1,
            format_func=lambda x: "🎯 Tentukan Manual (By Percentage Slider)" if x == "MANUAL" else "🤖 Diserahkan ke AI (Otomatis Multi-Armed Bandit)",
            key=f"radio_mode_{sel_acc_model}"
        )

        if choice_model_mode == "MANUAL":
            m1_slider_val = st.slider(
                f"Persentase Model 1 (Direct Link) untuk {sel_acc_model}:",
                min_value=0,
                max_value=100,
                value=cur_acc_m1,
                step=5,
                key=f"slider_m1_{sel_acc_model}",
                help="Sisa persentase otomatis menjadi jatah Model 2 (Link di Kolom Balasan)."
            )
            m2_slider_val = 100 - m1_slider_val

            c_m1_box, c_m2_box = st.columns(2)
            with c_m1_box:
                st.metric("Model 1 (Link di Post Utama)", f"{m1_slider_val}%")
            with c_m2_box:
                st.metric("Model 2 (Link di Kolom Balasan)", f"{m2_slider_val}%")
            st.progress(m1_slider_val / 100)
            st.caption(f"🔵 **Model 1:** {m1_slider_val}% | ⚪ **Model 2:** {m2_slider_val}%")
            final_m1_to_save = m1_slider_val
            final_m2_to_save = m2_slider_val
        else:
            final_m1_to_save = cur_acc_m1
            final_m2_to_save = 100 - cur_acc_m1
            st.info(
                f"💡 **Diserahkan ke AI:** Komposisi Model 1 dan Model 2 untuk akun `{sel_acc_model}` "
                f"akan diputuskan secara dinamis dan adaptif oleh AI (Multi-Armed Bandit) "
                f"berdasarkan data views dan performa historis nyata."
            )

        if st.button(f"💾 Simpan Komposisi Model ({sel_acc_model})", type="primary", key=f"btn_save_model_{sel_acc_model}"):
            sh_obj = get_spreadsheet()
            if sh_obj:
                try:
                    update_config_keys(sh_obj, {
                        f"model_decision_mode_{sel_acc_model}": choice_model_mode,
                        f"model_1_ratio_{sel_acc_model}": str(final_m1_to_save),
                        f"model_2_ratio_{sel_acc_model}": str(final_m2_to_save)
                    })
                    st.cache_data.clear()
                    st.success(f"✅ Pengaturan komposisi model untuk {sel_acc_model} berhasil disimpan ke Google Sheets!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal menyimpan ke Sheets: {e}")

    if acc_names_all:
        with st.expander("📋 Lihat Rekap Status Komposisi Model Semua Akun"):
            rekap_rows = []
            for a_name in acc_names_all:
                a_mode = cfg_data.get(f"model_decision_mode_{a_name}", cfg_data.get("model_decision_mode", "MANUAL")).upper()
                a_m1 = cfg_data.get(f"model_1_ratio_{a_name}", cfg_data.get("model_1_ratio", "30"))
                try:
                    a_m2 = str(100 - int(a_m1))
                except:
                    a_m2 = "70"
                rekap_rows.append({
                    "Akun": a_name,
                    "Mode": "🤖 Diserahkan ke AI" if a_mode == "AI_DYNAMIC" else "🎯 Manual",
                    "Model 1 (Direct)": f"{a_m1}%",
                    "Model 2 (Reply)": f"{a_m2}%"
                })
            st.dataframe(pd.DataFrame(rekap_rows), use_container_width=True, hide_index=True)

    st.divider()

    st.write("#### ⚡ Eksekusi Cepat: Generate Konten Hari Ini")
    if st.button("🚀 Generate Konten Autopilot Sekarang"):
        sh_obj = get_spreadsheet()
        if not sh_obj:
            st.error("Spreadsheet tidak tersedia.")
        else:
            with st.spinner(f"Sedang meracik {total_plan} konten dengan AI Self-Learning (Model 1 & Model 2)..."):
                try:
                    if not acc_records:
                        st.error("Daftarkan akun di tab Akun Threads terlebih dahulu.")
                    else:
                        target_accounts_to_run = acc_names_all if sel_auto_acc == "-- Semua Akun (All Accounts) --" else [sel_auto_acc]
                        ready_prods = [p for p in raw_prods if str(p.get("status", "")).strip().upper() == "READY"]
                        prods_with_media = [p for p in ready_prods if str(p.get("media_url", "")).strip()]
                        prods_text_only = [p for p in ready_prods if not str(p.get("media_url", "")).strip()] or ready_prods

                        today_str = now.strftime("%Y-%m-%d")
                        data_ws = sh_obj.worksheet("data")
                        new_rows = []

                        # AI Self-Learning & Bandit Engine Integration
                        model_stats = calculate_model_engagement_ratio(all_data)
                        learnings = extract_self_learning_patterns(all_data)
                        winning_copies = learnings["winning_copies"]
                        winning_products_map = learnings["winning_products"]

                        winning_context_prompt = ""
                        if winning_copies:
                            formatted_examples = "\n---\n".join(winning_copies[:2])
                            winning_context_prompt = (
                                f"\n[REFERENSI GAYA TULISAN ENGAGEMENT TERTINGGI]:\n{formatted_examples}\n"
                                f"(Tirulah ritme santainya tanpa menyalin kata per kata)\n"
                            )

                        def pick_weighted_product_app(prod_list):
                            if not prod_list:
                                return random.choice(ready_prods)
                            weights = []
                            for p in prod_list:
                                link = str(p.get("affiliate_link", "")).strip()
                                sc = winning_products_map.get(link, None)
                                if sc is None:
                                    w = 3.5
                                elif sc == 0:
                                    w = 1.2
                                else:
                                    w = 1.0 + min(sc / 150.0, 6.0)
                                weights.append(w)
                            return random.choices(prod_list, weights=weights, k=1)[0]

                        for acc_target in target_accounts_to_run:
                            for slot_time, p_type in zip(preview_slots, preview_types):
                                chosen_len = pick_length_by_bias(sel_bias_autopilot)
                                len_desc = get_length_prompt_desc(chosen_len)
                                style_desc = resolve_style_desc(sel_ai_style_ap)
                                direct_to_main = decide_post_model_for_account(acc_target, cfg_data, slot_time, all_data, model_stats)

                                if p_type == "viral":
                                    sub_top, angle_top = get_random_dynamic_topic()
                                    prompt_v = (
                                        f"Tulis 1 postingan Threads bahasa Indonesia tentang: '{sub_top}'.\n"
                                        f"Sudut pandang: {angle_top}.\n{winning_context_prompt}{PROMPT_RULES_CLEAN}\n{len_desc}\n"
                                        f"Maksimal 220 karakter. Langsung tulis teks postingan tanpa tanda kutip."
                                    )
                                    v_text = call_gemini(prompt_v)
                                    clean_v_text = sanitize_threads_text(v_text)
                                    new_rows.append([today_str, slot_time, acc_target, clean_v_text, "", "", "", "PENDING", "", "", "", ""])

                                elif p_type == "video":
                                    prod = pick_weighted_product_app(prods_with_media if prods_with_media else ready_prods)

                                    if direct_to_main:
                                        # Model 1: Penempatan Link Fleksibel (Awal / Tengah / Akhir) - 1 Post, Reply Kosong
                                        pos_rule = random.choice(MODEL_1_POSITION_PROMPTS)
                                        prompt_a = (
                                            f"Kamu adalah user Threads Indonesia yang santai, jujur, dan relate.\n"
                                            f"Tulis 1 postingan pengantar video untuk produk: '{prod['product_name']}' (Keunggulan: {prod.get('highlight', '')}).\n"
                                            f"{winning_context_prompt}\n"
                                            f"ATURAN KHUSUS:\n"
                                            f"1. {pos_rule}\n"
                                            f"2. Tulis placeholder persis: '[LINK_PRODUK]' (nanti sistem yang menempelkan link asli).\n"
                                            f"3. DILARANG pakai kata 'POV:', '[Teks Utama]', atau gaya iklan brosur kaku.\n"
                                            f"4. Maksimal 260 karakter tanpa tanda kutip."
                                        )
                                        raw_out = call_gemini(prompt_a)
                                        full_main_post = format_model_1_text(raw_out, prod["affiliate_link"])
                                        raw_m = str(prod.get("media_url", "")).strip()
                                        final_media = prepare_media_for_post(raw_m, duplicate_single_video=auto_dup_video)

                                        new_rows.append([today_str, slot_time, acc_target, full_main_post, final_media, "", prod["affiliate_link"], "PENDING", "", "", "", ""])
                                    else:
                                        # Model 2: Hook di post utama, Link di Reply
                                        chosen_hook = random.choice(VIRAL_HOOK_PATTERNS)
                                        prompt_a = (
                                            f"Tulis 1 postingan Threads bahasa Indonesia penahan jempol (stop scrolling) penonton video untuk produk: '{prod['product_name']}' "
                                            f"(Keunggulan: {prod.get('highlight', '')}).\n"
                                            f"- Formula Hook: {chosen_hook}\n"
                                            f"{winning_context_prompt}\n"
                                            f"- {style_desc}\n- {len_desc}\n{PROMPT_RULES_CLEAN}\n"
                                            f"Ingat: Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji pemantik rasa penasaran dalam 1-3 detik. Langsung tulis tanpa tanda kutip."
                                        )
                                        main_txt = call_gemini(prompt_a)
                                        clean_main_txt = sanitize_threads_text(main_txt)
                                        act_rep_count = resolve_reply_count(sel_reply_mode_ap)
                                        replies_chain = generate_affiliate_replies(prod['product_name'], prod.get('highlight', ''), prod['affiliate_link'], act_rep_count)
                                        raw_m = str(prod.get("media_url", "")).strip()
                                        final_media = prepare_media_for_post(raw_m, duplicate_single_video=auto_dup_video)

                                        new_rows.append([today_str, slot_time, acc_target, clean_main_txt, final_media, "\n---REPLY---\n".join(replies_chain), prod["affiliate_link"], "PENDING", "", "", "", ""])

                                else:
                                    prod = pick_weighted_product_app(prods_text_only)

                                    if direct_to_main:
                                        # Model 1 Teks Saja
                                        pos_rule = random.choice(MODEL_1_POSITION_PROMPTS)
                                        prompt_a = (
                                            f"Tulis 1 postingan teks Threads tentang produk: '{prod['product_name']}'.\n"
                                            f"Keunggulan: {prod.get('highlight', '')}. Vibe: {resolve_style_desc(sel_ai_style_ap)}.\n"
                                            f"{winning_context_prompt}\n"
                                            f"ATURAN KHUSUS:\n"
                                            f"1. {pos_rule}\n"
                                            f"2. Tulis placeholder persis: '[LINK_PRODUK]' (nanti sistem yang menempelkan link asli).\n"
                                            f"3. DILARANG pakai label '[Teks Utama]' atau 'POV:'.\n"
                                            f"4. Maksimal 260 karakter tanpa tanda kutip."
                                        )
                                        raw_out = call_gemini(prompt_a)
                                        full_main_post = format_model_1_text(raw_out, prod["affiliate_link"])
                                        new_rows.append([today_str, slot_time, acc_target, full_main_post, "", "", prod["affiliate_link"], "PENDING", "", "", "", ""])
                                    else:
                                        # Model 2 Teks Saja
                                        chosen_hook = random.choice(VIRAL_HOOK_PATTERNS)
                                        prompt_a = (
                                            f"Tulis 1 postingan Threads bahasa Indonesia rekomendasi teks tanpa media untuk produk: '{prod['product_name']}' "
                                            f"(Keunggulan: {prod.get('highlight', '')}).\n"
                                            f"- Formula Hook: {chosen_hook}\n"
                                            f"{winning_context_prompt}\n"
                                            f"- {style_desc}\n- {len_desc}\n{PROMPT_RULES_CLEAN}\n"
                                            f"Ingat: Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji pemantik rasa penasaran dalam 1-3 detik. Langsung tulis tanpa tanda kutip."
                                        )
                                        main_txt = call_gemini(prompt_a)
                                        clean_main_txt = sanitize_threads_text(main_txt)
                                        act_rep_count = resolve_reply_count(sel_reply_mode_ap)
                                        replies_chain = generate_affiliate_replies(prod['product_name'], prod.get('highlight', ''), prod['affiliate_link'], act_rep_count)

                                        new_rows.append([today_str, slot_time, acc_target, clean_main_txt, "", "\n---REPLY---\n".join(replies_chain), prod["affiliate_link"], "PENDING", "", "", "", ""])

                        for r in new_rows:
                            data_ws.append_row(r)

                        st.cache_data.clear()
                        st.success(f"🎉 Berhasil membuat {len(new_rows)} antrean postingan ber-hook viral (Model 1 & 2 terpadu)!")
                        st.rerun()
                except Exception as ex:
                    st.error(f"Terjadi kesalahan: {ex}")

# ==============================================================================
# TAB 2: HIJACK THREAD VIRAL (KOMENTAR VIDEO / TEKS)
# ==============================================================================
with tabs[1]:
    st.subheader("🎯 Thread Hijacking (Nimbrung di Postingan Viral)")
    st.caption("Balas postingan viral orang lain dengan komentar relate + video demo produk dari katalog, lalu selipkan link Shopee di balasan sendiri.")

    all_ready_p = [p for p in raw_prods if str(p.get("status", "")).strip().upper() == "READY"]
    acc_names_all = [str(a["name"]).strip() for a in acc_records if str(a.get("name", "")).strip()]

    c_hj1, c_hj2 = st.columns([2, 1])
    with c_hj1:
        viral_url_input = st.text_input(
            "🔗 Link Postingan Threads Viral atau Numeric Post ID:",
            placeholder="Contoh: https://www.threads.net/@namauser/post/C9xyz123 atau ID angka"
        )
    with c_hj2:
        hj_account = st.selectbox("Akun untuk Membalas:", acc_names_all if acc_names_all else ["Belum ada akun"], key="hj_acc")

    resolved_post_id = extract_threads_media_id(viral_url_input) if viral_url_input else ""
    if resolved_post_id:
        st.info(f"Target Media ID Terdeteksi: `{resolved_post_id}`")

    st.write("##### 💬 Konteks Obrolan di Postingan Viral Tersebut")
    viral_context_input = st.text_area(
        "Ceritakan singkat masalah/keluhan yang sedang ramai di postingan itu:",
        placeholder="Contoh: Banyak yang ngeluh wajan teflonnya gampang ngelupas dan lengket, atau pada debat capek nyikatin celah keramik kamar mandi yang berlumut.",
        height=90
    )

    col_hp1, col_hp2 = st.columns(2)
    with col_hp1:
        prod_hijack_options = ["-- Biarkan AI Memilih Otomatis yang Paling Cocok --"] + [p["product_name"] for p in all_ready_p]
        sel_hj_prod = st.selectbox("Pilih Produk Solusi dari Katalog:", prod_hijack_options)
    with col_hp2:
        hj_style = st.selectbox("Gaya Bahasa Nimbrung:", [
            "Curhat Relate & Nimbrung Santai (Khas Warganet Threads)",
            "Plot Twist & Pengalaman Pribadi (Dulu sama, sekarang beres)",
            "Spill Santai Solutif (Bocor Alus)"
        ])

    if st.button("✨ Racik Balasan Nimbrung via AI", type="primary"):
        if not viral_url_input or not resolved_post_id:
            st.error("Link atau ID postingan viral wajib diisi!")
        elif not viral_context_input.strip():
            st.error("Ketik ringkasan konteks postingan viral tersebut!")
        elif not all_ready_p:
            st.error("Katalog produk berstatus READY masih kosong.")
        else:
            with st.spinner("AI sedang menganalisis dan meracik komentar solutif..."):
                try:
                    if sel_hj_prod == "-- Biarkan AI Memilih Otomatis yang Paling Cocok --":
                        katalog_ringkas = "\n".join([f"- {p['product_name']}: {p.get('highlight', '')}" for p in all_ready_p[:20]])
                        prompt_pilih = (
                            f"Dari daftar produk ini:\n{katalog_ringkas}\n\n"
                            f"Pilih 1 produk yang paling NYAMBUNG dan bisa menjadi solusi untuk masalah ini: '{viral_context_input}'. "
                            f"Hanya tulis nama persis produk yang dipilih tanpa penjelasan lain."
                        )
                        terpilih_nama = call_gemini(prompt_pilih).strip().strip('"').strip("'")
                        target_prod = next((p for p in all_ready_p if p["product_name"].lower() in terpilih_nama.lower()), random.choice(all_ready_p))
                    else:
                        target_prod = next((p for p in all_ready_p if p["product_name"] == sel_hj_prod), all_ready_p[0])

                    p_name = target_prod["product_name"]
                    p_hl = target_prod.get("highlight", "")
                    p_link = target_prod.get("affiliate_link", "")
                    p_media = str(target_prod.get("media_url", "")).strip()

                    prompt_hijack = (
                        f"Tulis 1 komentar balasan Threads untuk nimbrung di postingan viral yang membahas: '{viral_context_input}'.\n"
                        f"Solusi yang kamu pakai: produk '{p_name}' (Keunggulan: {p_hl}).\n"
                        f"Gaya: {hj_style}.\n"
                        f"{PROMPT_RULES_CLEAN}\n"
                        f"ATURAN WAJIB:\n"
                        f"1. Seolah-olah kamu warganet biasa yang senasib dan relate.\n"
                        f"2. Ceritakan bagaimana benda kecil ini menyelesaikan masalah itu tanpa terkesan jualan.\n"
                        f"3. DILARANG sebut nama produk secara kaku (sebut 'alat ini', 'benda ini', atau 'printilan ini').\n"
                        f"4. DILARANG sebutkan link atau kata 'yuk beli' di komentar ini.\n"
                        f"Maksimal 180 karakter. Langsung tulis teks komentar tanpa tanda kutip."
                    )
                    main_comment = call_gemini(prompt_hijack)

                    prompt_spill = (
                        f"Tulis 1 baris balasan santai (maksimal 70 karakter) sebelum menyematkan link toko resmi pembelian '{p_name}'. "
                        f"Contoh tema: buat yang nanya di DM beli dimana, atau info toko officialnya. Tanpa hashtag, tanpa link."
                    )
                    spill_intro = call_gemini(prompt_spill).strip().strip('"').strip("'")
                    if not spill_intro or len(spill_intro) > 100:
                        spill_intro = random.choice(CLOSING_NARRATIVES)
                    reply_link_post = f"{spill_intro}\n{p_link}"

                    st.session_state["hijack_draft"] = {
                        "account": hj_account,
                        "target_id": resolved_post_id,
                        "main": main_comment,
                        "media": p_media,
                        "reply": reply_link_post,
                        "link": p_link,
                        "prod_name": p_name
                    }
                    st.success(f"🎉 Komentar balasan berhasil diracik dengan rekomendasi solusi: **{p_name}**!")
                except Exception as ex:
                    st.error(f"Gagal generate: {ex}")

    if "hijack_draft" in st.session_state and st.session_state["hijack_draft"]:
        d = st.session_state["hijack_draft"]
        st.divider()
        st.write("#### 📝 Preview Balasan Komentar & Video")
        st.caption(f"Akan membalas Post ID: `{d['target_id']}` menggunakan akun `{d['account']}`.")

        col_pv1, col_pv2 = st.columns(2)
        with col_pv1:
            d["main"] = st.text_area("1. Komentar Nimbrung (Teks Postingan Balasan):", value=d["main"], height=100)
            d["media"] = st.text_input("Media URL Video/Foto (Cloudinary):", value=d.get("media", ""), help="Kosongkan jika hanya ingin komentar teks saja.")
        with col_pv2:
            d["reply"] = st.text_area("2. Balasan di Bawah Komentar Sendiri (Spill Link):", value=d["reply"], height=100)
            st.info(f"Produk Terpilih: **{d.get('prod_name', '-')}**\n\nLink: `{d.get('link', '-')}`")

        if st.button("🚀 Kirim Komentar (Dengan Video) ke Antrean", type="primary"):
            sh_obj = get_spreadsheet()
            if sh_obj:
                try:
                    data_ws = sh_obj.worksheet("data")
                    now_str_date = now.strftime("%Y-%m-%d")
                    now_str_time = (now - timedelta(minutes=2)).strftime("%H:%M")

                    data_ws.append_row([
                        now_str_date,
                        now_str_time,
                        d["account"],
                        d["main"],
                        d.get("media", ""),
                        d["reply"],
                        d["link"],
                        "PENDING",
                        "", "", "",
                        d["target_id"]
                    ])
                    st.cache_data.clear()
                    st.success("🎉 Berhasil disimpan ke antrean Google Sheets lengkap dengan video! Jalankan worker untuk menerbitkan.")
                    st.session_state["hijack_draft"] = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal menyimpan ke Sheets: {e}")

# ==============================================================================
# TAB 3: KATALOG PRODUK
# ==============================================================================
with tabs[2]:
    st.subheader("📦 Katalog Produk Affiliate")
    expected_cols = ["product_name", "highlight", "affiliate_link", "category", "status", "media_url"]

    if raw_prods:
        df_prods = pd.DataFrame(raw_prods)
        for col in expected_cols:
            if col not in df_prods.columns:
                df_prods[col] = ""
        df_prods = df_prods[expected_cols]
    else:
        df_prods = pd.DataFrame(columns=expected_cols)

    total_items = len(df_prods)
    ready_items = len(df_prods[df_prods["status"].astype(str).str.upper() == "READY"]) if not df_prods.empty else 0
    media_items = len(df_prods[df_prods["media_url"].astype(str).str.strip() != ""]) if not df_prods.empty else 0

    c_m1, c_m2, c_m3 = st.columns(3)
    c_m1.metric("Total Produk Terdaftar", f"{total_items} Item")
    c_m2.metric("Produk READY", f"{ready_items} Item")
    c_m3.metric("Produk Memiliki Media", f"{media_items} Item")

    st.divider()
    st.write("#### 📝 Edit Langsung di Tabel (Excel Style)")

    edited_df = st.data_editor(
        df_prods,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "product_name": st.column_config.TextColumn("Nama Produk", required=True, width="medium"),
            "highlight": st.column_config.TextColumn("Keunggulan / Highlight", width="large"),
            "affiliate_link": st.column_config.TextColumn("Link Affiliate Shopee", required=True, width="medium"),
            "category": st.column_config.TextColumn("Kategori", width="small"),
            "status": st.column_config.SelectboxColumn("Status", options=["READY", "DRAFT", "ARCHIVED"], required=True, width="small"),
            "media_url": st.column_config.TextColumn("Media URL (Cloudinary)", width="large")
        },
        height=350
    )

    if st.button("💾 Simpan Semua Perubahan Tabel", type="primary"):
        sh_obj = get_spreadsheet()
        if sh_obj:
            with st.spinner("Menyimpan katalog ke Google Sheets..."):
                try:
                    prod_ws = sh_obj.worksheet("Products")
                    prod_ws.clear()
                    header = [expected_cols]
                    data_rows = edited_df.fillna("").values.tolist()
                    prod_ws.update(header + data_rows)
                    st.cache_data.clear()
                    st.success("✅ Katalog berhasil diperbarui sepenuhnya!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal menyimpan ke Sheets: {e}")

# ==============================================================================
# TAB 4: CONTENT STUDIO (MANUAL & AI)
# ==============================================================================
with tabs[3]:
    st.subheader("✍️ Content Studio (Pembuat Konten Manual & AI)")
    st.caption("Pusat pembuatan postingan mandiri atau paket kombinasi harian dengan variasi hook viral 1-3 detik.")

    if "manual_generated_posts" not in st.session_state:
        st.session_state["manual_generated_posts"] = []

    st.write("#### ⚙️ 1. Pengaturan Jadwal & Frekuensi")
    c_set1, c_set2, c_set3, c_set4 = st.columns(4)
    with c_set1:
        target_account = st.selectbox("🎯 Target Akun Threads", ["-- Semua Akun (All Accounts) --"] + acc_names_all)
    with c_set2:
        schedule_d = st.date_input("📅 Tanggal Mulai", value=now.date(), key="cs_date")
    with c_set3:
        schedule_t = st.time_input("⏰ Jam Mulai", value=now.time(), key="cs_time")
    with c_set4:
        interval_mins = st.selectbox("⏳ Selang Waktu", [60, 120, 180, 240, 360, 480, 720, 1440], index=1, format_func=lambda x: f"{x // 60} Jam Sekali" if x < 1440 else "1 Hari Sekali")

    c_fmt1, c_fmt2 = st.columns(2)
    with c_fmt1:
        manual_length_opt = st.selectbox("📏 Panjang Teks", ["Sedang (180-260 karakter)", "Pendek (max 140 karakter)", "Panjang (300-450 karakter)", "🎲 Acak Sesuai AI"])
    with c_fmt2:
        manual_reply_mode = st.selectbox("💬 Rantai Balasan", ["1 Balasan (Hanya Link)", "2 Balasan (1 Cerita + Link)", "3 Balasan (2 Cerita + Link)", "🎲 Acak (1 - 3 Balasan)"])

    st.divider()
    content_mode = st.radio("Pilih Mode Konten:", ["🎯 Paket Kombinasi Harian (Video + Teks + Viral)", "🛍️ Single Product Affiliate", "🚀 Viral Booster", "✍️ Tulis Bebas Manual"], horizontal=True)

    copy_styles = ["Serahkan ke AI", "Curhat Santai & Relate", "Storytelling Pengalaman Pribadi", "Review Jujur & Solutif", "Racun Belanja Shopee"]

    if content_mode == "🎯 Paket Kombinasi Harian (Video + Teks + Viral)":
        ck1, ck2, ck3 = st.columns(3)
        with ck1:
            cb_video = st.number_input("Jumlah Video", 0, 50, min(max(4, 0), 50), key="cb_v")
        with ck2:
            cb_text = st.number_input("Jumlah Teks", 0, 50, min(max(3, 0), 50), key="cb_t")
        with ck3:
            cb_viral = st.number_input("Jumlah Viral", 0, 50, min(max(3, 0), 50), key="cb_vi")

        cb_style = st.selectbox("Gaya Bahasa AI:", copy_styles, key="cb_style")
        cb_dup_video = st.checkbox("🎬 Trik Thumbnail 2 Video (Carousel)", value=True, key="cb_dup")

        if st.button("✨ Generate Paket Kombinasi via AI", type="primary"):
            prods_with_media = [p for p in all_ready_p if str(p.get("media_url", "")).strip()]
            prods_text_only = [p for p in all_ready_p if not str(p.get("media_url", "")).strip()] or all_ready_p
            tot_combo = cb_video + cb_text + cb_viral

            if tot_combo > 0:
                with st.spinner(f"Meracik {tot_combo} postingan dengan variasi hook viral..."):
                    base_dt = datetime.combine(schedule_d, schedule_t)
                    post_types = arrange_post_types_3way(cb_viral, cb_text, cb_video)
                    gen_list = []

                    sampled_video = random.sample(prods_with_media, min(cb_video, len(prods_with_media))) if (cb_video > 0 and prods_with_media) else []
                    sampled_text = random.sample(prods_text_only, min(cb_text, len(prods_text_only))) if (cb_text > 0 and prods_text_only) else []

                    v_i, t_i = 0, 0
                    for idx_c, p_t in enumerate(post_types):
                        p_dt = base_dt + timedelta(minutes=idx_c * interval_mins)
                        act_len = random.choice(["Pendek", "Sedang", "Panjang"]) if "Acak" in manual_length_opt else manual_length_opt
                        len_desc = get_length_prompt_desc(act_len)
                        style_desc = resolve_style_desc(cb_style)

                        if p_t == "viral":
                            sub_top, angle_top = get_random_dynamic_topic()
                            prompt_v = f"Tulis 1 postingan Threads bahasa Indonesia tentang: '{sub_top}'. Sudut pandang: {angle_top}.\n{PROMPT_RULES_CLEAN}\n{len_desc}\nMaksimal 220 karakter tanpa kutip."
                            v_txt = call_gemini(prompt_v)
                            gen_list.append({"date": p_dt.strftime("%Y-%m-%d"), "time": p_dt.strftime("%H:%M"), "account": target_account, "main": v_txt, "media": "", "reply": "", "link": ""})
                        elif p_t == "video":
                            p_cur = sampled_video[v_i] if v_i < len(sampled_video) else random.choice(all_ready_p)
                            v_i += 1
                            chosen_hook = random.choice(VIRAL_HOOK_PATTERNS)
                            prompt_a = (
                                f"Tulis 1 postingan Threads bahasa Indonesia penahan jempol (stop scrolling) penonton video untuk produk: '{p_cur['product_name']}' (Keunggulan: {p_cur.get('highlight', '')}).\n"
                                f"- Formula Hook: {chosen_hook}\n- {style_desc}\n- {len_desc}\n{PROMPT_RULES_CLEAN}\n"
                                f"Ingat: Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji pemantik rasa penasaran dalam 1-3 detik. Langsung tulis teks tanpa tanda kutip."
                            )
                            m_txt = call_gemini(prompt_a)
                            replies = generate_affiliate_replies(p_cur['product_name'], p_cur.get('highlight', ''), p_cur['affiliate_link'], resolve_reply_count(manual_reply_mode))
                            raw_m = str(p_cur.get("media_url", "")).strip()
                            gen_list.append({"date": p_dt.strftime("%Y-%m-%d"), "time": p_dt.strftime("%H:%M"), "account": target_account, "main": m_txt, "media": prepare_media_for_post(raw_m, duplicate_single_video=cb_dup_video), "reply": "\n---REPLY---\n".join(replies), "link": p_cur["affiliate_link"]})
                        else:
                            p_cur = sampled_text[t_i] if t_i < len(sampled_text) else random.choice(all_ready_p)
                            t_i += 1
                            chosen_hook = random.choice(VIRAL_HOOK_PATTERNS)
                            prompt_a = (
                                f"Tulis 1 postingan Threads bahasa Indonesia rekomendasi teks tanpa media untuk produk: '{p_cur['product_name']}' (Keunggulan: {p_cur.get('highlight', '')}).\n"
                                f"- Formula Hook: {chosen_hook}\n- {style_desc}\n- {len_desc}\n{PROMPT_RULES_CLEAN}\n"
                                f"Ingat: Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji pemantik rasa penasaran dalam 1-3 detik. Langsung tulis teks tanpa tanda kutip."
                            )
                            m_txt = call_gemini(prompt_a)
                            replies = generate_affiliate_replies(p_cur['product_name'], p_cur.get('highlight', ''), p_cur['affiliate_link'], resolve_reply_count(manual_reply_mode))
                            gen_list.append({"date": p_dt.strftime("%Y-%m-%d"), "time": p_dt.strftime("%H:%M"), "account": target_account, "main": m_txt, "media": "", "reply": "\n---REPLY---\n".join(replies), "link": p_cur["affiliate_link"]})

                    st.session_state["manual_generated_posts"] = gen_list
                    st.success(f"🎉 Berhasil membuat {len(gen_list)} draf!")

    elif content_mode == "🛍️ Single Product Affiliate":
        c_sp1, c_sp2 = st.columns(2)
        with c_sp1:
            sel_sp = st.selectbox("Pilih Produk:", ["-- Acak dari Katalog READY --"] + [p["product_name"] for p in all_ready_p])
        with c_sp2:
            sp_style = st.selectbox("Gaya Bahasa AI:", copy_styles, key="sp_style")
            sp_dup_v = st.checkbox("🎬 Trik Thumbnail 2 Video (Carousel)", value=True, key="sp_dup")

        if st.button("✨ Generate Single Product Post", type="primary"):
            p_cur = random.choice(all_ready_p) if sel_sp == "-- Acak dari Katalog READY --" else next((p for p in all_ready_p if p["product_name"] == sel_sp), all_ready_p[0])
            act_len = random.choice(["Pendek", "Sedang", "Panjang"]) if "Acak" in manual_length_opt else manual_length_opt
            chosen_hook = random.choice(VIRAL_HOOK_PATTERNS)
            prompt = (
                f"Tulis 1 postingan Threads bahasa Indonesia penahan jempol (stop scrolling) untuk produk: '{p_cur['product_name']}' (Keunggulan: {p_cur.get('highlight', '')}).\n"
                f"- Formula Hook: {chosen_hook}\n- {resolve_style_desc(sp_style)}\n- {get_length_prompt_desc(act_len)}\n{PROMPT_RULES_CLEAN}\n"
                f"Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji pemantik rasa penasaran dalam 1-3 detik. Langsung tulis teks tanpa tanda kutip."
            )
            m_txt = call_gemini(prompt)
            replies = generate_affiliate_replies(p_cur['product_name'], p_cur.get('highlight', ''), p_cur['affiliate_link'], resolve_reply_count(manual_reply_mode))
            raw_m = str(p_cur.get("media_url", "")).strip()

            st.session_state["manual_generated_posts"] = [{
                "date": schedule_d.strftime("%Y-%m-%d"),
                "time": schedule_t.strftime("%H:%M"),
                "account": target_account,
                "main": m_txt,
                "media": prepare_media_for_post(raw_m, duplicate_single_video=sp_dup_v),
                "reply": "\n---REPLY---\n".join(replies),
                "link": p_cur["affiliate_link"]
            }]
            st.success("🎉 Draf berhasil dibuat!")

    elif content_mode == "🚀 Viral Booster":
        vb_topic = st.text_input("Topik (Kosongkan jika ingin acak otomatis):", placeholder="Misal: Etika membatalkan janji mendadak")
        if st.button("✨ Generate Postingan Viral", type="primary"):
            sub_top, angle_top = (vb_topic, "Opini santai") if vb_topic.strip() else get_random_dynamic_topic()
            act_len = random.choice(["Pendek", "Sedang", "Panjang"]) if "Acak" in manual_length_opt else manual_length_opt
            prompt_v = f"Tulis 1 postingan Threads bahasa Indonesia tentang: '{sub_top}'. Sudut pandang: {angle_top}.\n{PROMPT_RULES_CLEAN}\n{get_length_prompt_desc(act_len)}\nMaksimal 220 karakter tanpa kutip."
            v_txt = call_gemini(prompt_v)
            st.session_state["manual_generated_posts"] = [{
                "date": schedule_d.strftime("%Y-%m-%d"),
                "time": schedule_t.strftime("%H:%M"),
                "account": target_account,
                "main": v_txt,
                "media": "",
                "reply": "",
                "link": ""
            }]
            st.success("🎉 Postingan viral berhasil dibuat!")

    elif content_mode == "✍️ Tulis Bebas Manual":
        c_man1, c_man2 = st.columns(2)
        with c_man1:
            man_main = st.text_area("Teks Utama", height=100)
            man_media = st.text_input("Media URL")
        with c_man2:
            man_reply = st.text_area("Balasan (Pisahkan dengan ---REPLY---)", height=100)
            man_link = st.text_input("Link Shopee")

        if st.button("➕ Tambah Manual"):
            st.session_state["manual_generated_posts"].append({
                "date": schedule_d.strftime("%Y-%m-%d"),
                "time": schedule_t.strftime("%H:%M"),
                "account": target_account,
                "main": man_main.strip(),
                "media": man_media.strip(),
                "reply": man_reply.strip(),
                "link": man_link.strip()
            })
            st.success("✅ Ditambahkan!")

    # PREVIEW & SIMPAN
    posts_to_show = st.session_state.get("manual_generated_posts", [])
    if posts_to_show:
        st.divider()
        st.write("#### 📝 Preview Antrean Draf")
        for idx_p, p_item in enumerate(posts_to_show):
            with st.container():
                st.markdown(f"**📌 Post #{idx_p + 1} | `{p_item['date']} {p_item['time']}` | Target: `{p_item['account']}`**")
                col_box1, col_box2 = st.columns(2)
                with col_box1:
                    p_item["main"] = st.text_area(f"Teks #{idx_p + 1}", value=p_item["main"], height=90, key=f"preview_main_{idx_p}")
                    p_item["media"] = st.text_input(f"Media #{idx_p + 1}", value=p_item.get("media", ""), key=f"preview_media_{idx_p}")
                with col_box2:
                    p_item["reply"] = st.text_area(f"Reply #{idx_p + 1}", value=p_item["reply"], height=90, key=f"preview_reply_{idx_p}")
                    p_item["link"] = st.text_input(f"Link #{idx_p + 1}", value=p_item["link"], key=f"preview_link_{idx_p}")

        col_b1, col_b2 = st.columns([2, 1])
        with col_b1:
            if st.button("💾 Simpan Semua ke Google Sheets", type="primary"):
                sh_obj = get_spreadsheet()
                if sh_obj:
                    data_ws = sh_obj.worksheet("data")
                    accounts_to_save = acc_names_all if target_account == "-- Semua Akun (All Accounts) --" else [target_account]
                    for acc_name_single in accounts_to_save:
                        for itm in posts_to_show:
                            data_ws.append_row([
                                itm["date"],
                                itm["time"],
                                acc_name_single,
                                itm["main"],
                                itm.get("media", ""),
                                itm["reply"],
                                itm["link"],
                                "PENDING",
                                "", "", "", ""
                            ])
                    st.cache_data.clear()
                    st.success("🎉 Draf berhasil disimpan ke antrean!")
                    st.session_state["manual_generated_posts"] = []
                    st.rerun()
        with col_b2:
            if st.button("🗑️ Kosongkan Draf"):
                st.session_state["manual_generated_posts"] = []
                st.rerun()

# ==============================================================================
# TAB 5: ANTREAN & RIWAYAT
# ==============================================================================
with tabs[4]:
    st.subheader("📋 Daftar Antrean & Status Postingan")
    if all_data:
        st.dataframe(all_data, use_container_width=True)
    else:
        st.info("Belum ada antrean di tab data.")

# ==============================================================================
# TAB 6: AKUN THREADS & DIAGNOSTIK
# ==============================================================================
with tabs[5]:
    st.subheader("⚙ Manajemen Akun Threads & Diagnostik")
    if acc_records:
        df_acc = pd.DataFrame(acc_records)
        if "access_token" in df_acc.columns:
            df_acc["token_preview"] = df_acc["access_token"].apply(lambda t: str(t)[:10] + "..." + str(t)[-6:] if len(str(t)) > 16 else "********")
            st.dataframe(df_acc[["name", "user_id", "token_preview"]], use_container_width=True)
        else:
            st.dataframe(df_acc, use_container_width=True)

    st.divider()
    c_diag1, c_diag2 = st.columns(2)
    with c_diag1:
        st.write("##### 🧵 Tes Koneksi Threads")
        if acc_records:
            acc_to_test = st.selectbox("Pilih Akun:", [a["name"] for a in acc_records], key="sel_test_acc")
            if st.button("🔍 Tes Token"):
                chosen_acc = next((a for a in acc_records if a["name"] == acc_to_test), None)
                if chosen_acc:
                    res = check_threads_token(str(chosen_acc["user_id"]), str(chosen_acc["access_token"]))
                    if "id" in res:
                        st.success(f"✅ Token Aktif! (@{res.get('username')})")
                    else:
                        st.error(f"❌ Gagal: {res}")
    with c_diag2:
        st.write("##### 🤖 Tes Koneksi Gemini AI")
        if st.button("⚡ Tes Gemini"):
            try:
                reply, model = call_gemini_core("Tes koneksi!")
                st.success(f"✅ Terhubung ({model}): {reply}")
            except Exception as e:
                st.error(f"❌ Gagal: {e}")

    st.divider()
    st.write("#### ➕ Tambah Akun Threads Baru")
    with st.form("form_add_acc"):
        col_acc1, col_acc2 = st.columns(2)
        with col_acc1:
            new_acc_name = st.text_input("Nama Label Akun *", placeholder="Misal: akun_kedua")
            new_acc_uid = st.text_input("Threads User ID *", placeholder="17841...")
        with col_acc2:
            new_acc_token = st.text_area("Long-Lived Access Token *", height=90)
        btn_add = st.form_submit_button("💾 Simpan Akun")
        if btn_add:
            if new_acc_name and new_acc_uid and new_acc_token:
                sh_obj = get_spreadsheet()
                if sh_obj:
                    acc_ws = sh_obj.worksheet("Accounts")
                    acc_ws.append_row([new_acc_name.strip(), new_acc_uid.strip(), new_acc_token.strip()])
                    st.cache_data.clear()
                    st.success("✅ Akun tersimpan!")
                    st.rerun()

# ==============================================================================
# TAB 7: ANALISA DATA & AI SELF-LEARNING (FORMAT SESUAI MOCKUP DASHBOARD)
# ==============================================================================
with tabs[6]:
    st.subheader("📊 Analisa Engagement & AI Self-Learning")
    st.caption("Pantau performa postingan riil dari Threads API. Data ini digunakan oleh AI untuk mengoptimalkan hook, balasan CTA, dan produk unggulan.")

    if not all_data:
        st.info("Belum ada data postingan di spreadsheet.")
    else:
        df_raw = pd.DataFrame(all_data)

        date_col = next((c for c in df_raw.columns if any(k in c.lower() for k in ["date", "tanggal"])), None)
        time_col = next((c for c in df_raw.columns if any(k in c.lower() for k in ["time", "jam"])), None)
        acc_col = next((c for c in df_raw.columns if any(k in c.lower() for k in ["account", "akun"])), None)
        text_col = next((c for c in df_raw.columns if any(k in c.lower() for k in ["text", "main", "post", "isi"])), None)
        reply_col = next((c for c in df_raw.columns if "reply" in c.lower()), None)
        link_col = next((c for c in df_raw.columns if any(k in c.lower() for k in ["link", "affiliate", "shopee"])), None)
        stat_col = next((c for c in df_raw.columns if c.strip().lower() == "status"), None)

        for m in ["views", "likes", "replies", "reposts"]:
            m_col = next((c for c in df_raw.columns if c.strip().lower() == m), None)
            if m_col:
                df_raw[m_col] = pd.to_numeric(
                    df_raw[m_col].astype(str).str.replace(",", "").replace("", "0"),
                    errors="coerce"
                ).fillna(0).astype(int)
            else:
                df_raw[m] = 0

        v_col = next((c for c in df_raw.columns if c.strip().lower() == "views"), "views")
        l_col = next((c for c in df_raw.columns if c.strip().lower() == "likes"), "likes")
        r_col = next((c for c in df_raw.columns if c.strip().lower() == "replies"), "replies")
        rp_col = next((c for c in df_raw.columns if c.strip().lower() == "reposts"), "reposts")

        if date_col:
            df_raw["_parsed_date"] = pd.to_datetime(df_raw[date_col].astype(str).str.strip(), errors="coerce").dt.date
        else:
            df_raw["_parsed_date"] = date.today()

        if stat_col:
            df_base = df_raw[df_raw[stat_col].astype(str).str.upper() == "POSTED"].copy()
        else:
            df_base = df_raw.copy()

        # CONTROL & FILTER BAR
        st.markdown("#### 🎛️ Filter Analitik")
        f_col1, f_col2, f_col3, f_col4 = st.columns([2, 2, 2, 1])

        with f_col1:
            time_filter = st.selectbox(
                "📅 Rentang Waktu:",
                ["Last 30 Days", "Last 7 Days", "Today", "Semua Waktu", "Custom Range"],
                index=0
            )

        with f_col2:
            acc_filter_opts = ["@all_accounts (Semua)"] + acc_names_all
            selected_acc_filter = st.selectbox("👤 Akun Threads:", acc_filter_opts, index=0)

        with f_col3:
            model_filter = st.selectbox(
                "🎯 Format / Model:",
                ["Semua Format", "Model 1 (Direct Link)", "Model 2 (Reply Link)"],
                index=0
            )

        with f_col4:
            st.write("")
            st.write("")
            btn_refresh = st.button("🔄 Refresh", use_container_width=True)
            if btn_refresh:
                st.cache_data.clear()
                st.rerun()

        today_date = date.today()
        start_filter_date = today_date - timedelta(days=30)
        end_filter_date = today_date

        if time_filter == "Today":
            start_filter_date = today_date
            end_filter_date = today_date
        elif time_filter == "Last 7 Days":
            start_filter_date = today_date - timedelta(days=7)
            end_filter_date = today_date
        elif time_filter == "Last 30 Days":
            start_filter_date = today_date - timedelta(days=30)
            end_filter_date = today_date
        elif time_filter == "Semua Waktu":
            start_filter_date = date(2020, 1, 1)
            end_filter_date = date(2035, 12, 31)
        elif time_filter == "Custom Range":
            custom_dates = st.date_input("Pilih Tanggal Mulai & Akhir:", value=(start_filter_date, end_filter_date))
            if isinstance(custom_dates, tuple) and len(custom_dates) == 2:
                start_filter_date, end_filter_date = custom_dates

        df_filtered = df_base.copy()

        df_filtered = df_filtered[
            (df_filtered["_parsed_date"] >= start_filter_date) &
            (df_filtered["_parsed_date"] <= end_filter_date)
        ]

        if selected_acc_filter != "@all_accounts (Semua)" and acc_col:
            df_filtered = df_filtered[df_filtered[acc_col].astype(str).str.strip() == selected_acc_filter]

        if model_filter != "Semua Format":
            if model_filter == "Model 1 (Direct Link)":
                df_filtered = df_filtered[df_filtered[reply_col].astype(str).str.strip().isin(["", "nan", "None"])]
            else:
                df_filtered = df_filtered[~df_filtered[reply_col].astype(str).str.strip().isin(["", "nan", "None"])]

        period_days = max(1, (end_filter_date - start_filter_date).days + 1)
        prev_start = start_filter_date - timedelta(days=period_days)
        prev_end = start_filter_date - timedelta(days=1)
        df_prev = df_base[
            (df_base["_parsed_date"] >= prev_start) &
            (df_base["_parsed_date"] <= prev_end)
        ]
        if selected_acc_filter != "@all_accounts (Semua)" and acc_col:
            df_prev = df_prev[df_prev[acc_col].astype(str).str.strip() == selected_acc_filter]

        def calc_delta_str(curr_val, prev_val):
            if prev_val == 0:
                return "+0.0%" if curr_val == 0 else "+100%"
            pct = ((curr_val - prev_val) / prev_val) * 100
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.1f}%"

        tot_views = int(df_filtered[v_col].sum())
        tot_likes = int(df_filtered[l_col].sum())
        tot_rep = int(df_filtered[r_col].sum())
        tot_rp = int(df_filtered[rp_col].sum())
        tot_success = len(df_filtered)

        delta_v = calc_delta_str(tot_views, int(df_prev[v_col].sum()))
        delta_l = calc_delta_str(tot_likes, int(df_prev[l_col].sum()))
        delta_r = calc_delta_str(tot_rep, int(df_prev[r_col].sum()))
        delta_rp = calc_delta_str(tot_rp, int(df_prev[rp_col].sum()))
        delta_s = calc_delta_str(tot_success, len(df_prev))

        st.markdown("---")

        # KPI CARDS DENGAN DELTA
        c_kpi1, c_kpi2, c_kpi3, c_kpi4, c_kpi5 = st.columns(5)
        c_kpi1.metric("Total Views", f"{tot_views:,}", delta=delta_v)
        c_kpi2.metric("Total Likes", f"{tot_likes:,}", delta=delta_l)
        c_kpi3.metric("Total Replies", f"{tot_rep:,}", delta=delta_r)
        c_kpi4.metric("Total Reposts", f"{tot_rp:,}", delta=delta_rp)
        c_kpi5.metric("Post Sukses", f"{tot_success:,}", delta=delta_s)

        st.markdown("---")

        # BARIS 1: ENGAGEMENT TRAFFIC & WINNING HOOK COPIES
        col_trf, col_hk = st.columns([1, 1])

        with col_trf:
            st.markdown("##### 📈 ENGAGEMENT TRAFFIC (Daily Views)")
            st.caption("Tren views harian terakumulasi dari postingan berstatus POSTED:")
            if not df_filtered.empty and tot_views > 0:
                daily_trend = df_filtered.groupby("_parsed_date")[v_col].sum().reset_index()
                daily_trend.rename(columns={"_parsed_date": "Tanggal", v_col: "Views"}, inplace=True)
                daily_trend["Tanggal"] = daily_trend["Tanggal"].astype(str)
                st.line_chart(daily_trend.set_index("Tanggal")["Views"], height=280)
            else:
                st.info("Belum ada data traffic views pada rentang filter ini.")

        with col_hk:
            st.markdown("##### 🏆 WINNING HOOK COPIES (TOP 5)")
            st.caption("Postingan dengan jangkauan views & interaksi tertinggi:")
            if not df_filtered.empty and tot_views > 0:
                top5 = df_filtered.sort_values(by=v_col, ascending=False).head(5)
                for rank_idx, (_, row) in enumerate(top5.iterrows(), start=1):
                    v_val = int(row.get(v_col, 0))
                    l_val = int(row.get(l_col, 0))
                    r_val = int(row.get(r_col, 0))
                    d_val = str(row.get(date_col, "")) if date_col else ""
                    t_val = str(row.get(time_col, "")) if time_col else ""
                    main_t = str(row.get(text_col, "")) if text_col else ""
                    rep_t = str(row.get(reply_col, "")) if reply_col else ""

                    with st.expander(f"#{rank_idx} 👁️ {v_val:,} Views | ❤️ {l_val:,} | 💬 {r_val:,} — {d_val} {t_val}"):
                        st.markdown(f"**Teks Postingan Utama:**\n\n> {main_t}")
                        if rep_t and rep_t.lower() != "nan":
                            st.markdown(f"**Balasan (Reply CTA):**\n\n`{rep_t}`")
            else:
                st.info("Belum ada data riwayat postingan yang cukup untuk ditampilkan.")

        st.markdown("---")

        # BARIS 2: WINNING AFFILIATE PRODUCTS & PEAK POSTING HOURS
        col_prod, col_hours = st.columns([1, 1])

        with col_prod:
            st.markdown("##### 🛒 WINNING AFFILIATE PRODUCTS")
            st.caption("Akumulasi views tertinggi berdasarkan produk / link affiliate:")
            if not df_filtered.empty and link_col:
                valid_links = df_filtered[df_filtered[link_col].astype(str).str.strip().str.startswith("http")]
                if not valid_links.empty:
                    prod_stats = valid_links.groupby(link_col).agg(
                        Total_Views=(v_col, "sum"),
                        Total_Likes=(l_col, "sum"),
                        Total_Post=(v_col, "count")
                    ).reset_index()

                    if raw_prods:
                        df_p_meta = pd.DataFrame(raw_prods)
                        p_link_meta = next((c for c in df_p_meta.columns if any(k in c.lower() for k in ["link", "affiliate"])), None)
                        p_name_meta = next((c for c in df_p_meta.columns if any(k in c.lower() for k in ["name", "nama", "product"])), None)
                        p_cat_meta = next((c for c in df_p_meta.columns if "cat" in c.lower()), None)

                        if p_link_meta and p_name_meta:
                            cols_to_merge = [p_name_meta, p_link_meta]
                            if p_cat_meta:
                                cols_to_merge.append(p_cat_meta)
                            prod_stats = pd.merge(prod_stats, df_p_meta[cols_to_merge], left_on=link_col, right_on=p_link_meta, how="left")
                            prod_stats["Product"] = prod_stats[p_name_meta].fillna(prod_stats[link_col])
                            prod_stats["Category"] = prod_stats[p_cat_meta].fillna("General") if p_cat_meta else "General"
                        else:
                            prod_stats["Product"] = prod_stats[link_col]
                            prod_stats["Category"] = "General"
                    else:
                        prod_stats["Product"] = prod_stats[link_col]
                        prod_stats["Category"] = "General"

                    prod_stats = prod_stats.sort_values(by="Total_Views", ascending=False).head(10)
                    display_df = prod_stats[["Product", "Category", "Total_Views", "Total_Post", link_col]].rename(
                        columns={"Total_Views": "Views", "Total_Post": "Posts", link_col: "Link"}
                    )

                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Views": st.column_config.NumberColumn("Total Views", format="%d"),
                            "Posts": st.column_config.NumberColumn("Jumlah Post", format="%d"),
                            "Link": st.column_config.LinkColumn("Tautan Lapak")
                        },
                        height=260
                    )
                else:
                    st.info("Belum ada link produk yang memiliki views pada filter ini.")
            else:
                st.info("Data produk belum mencukupi.")

        with col_hours:
            st.markdown("##### ⏰ PEAK POSTING HOURS (WIB)")
            st.caption("Rata-rata views postingan berdasarkan jam tayang:")
            if not df_filtered.empty and time_col:
                df_filtered["hour_num"] = df_filtered[time_col].astype(str).apply(
                    lambda x: str(x).split(":")[0].zfill(2) if ":" in str(x) else "00"
                )
                hourly = df_filtered.groupby("hour_num")[v_col].mean().reset_index()
                hourly["Jam"] = hourly["hour_num"].apply(lambda h: f"{h}:00")
                st.bar_chart(hourly.set_index("Jam")[v_col], height=260)
            else:
                st.info("Data jam postingan belum tersedia.")

        st.divider()
        csv_export = df_filtered.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Unduh Data Analitik (CSV)",
            data=csv_export,
            file_name=f"threads_analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=False
        )
