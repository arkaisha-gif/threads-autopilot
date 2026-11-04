import os
import re
import json
import base64
import time
import random
from datetime import datetime, timedelta
import pytz
import requests
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

TZ = pytz.timezone("Asia/Jakarta")

# ==========================================
# PENGAMBILAN KREDENSIAL & SECRETS
# ==========================================
def get_secret(key, default=""):
    val = os.environ.get(key)
    if val:
        return val
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

SPREADSHEET_ID = get_secret("SPREADSHEET_ID")
GCP_CREDS_BASE64 = get_secret("GCP_CREDS_BASE64")
AI_API_KEY = (
    get_secret("AI_API_KEY")
    or os.environ.get("GEMINI_API_KEY")
    or os.environ.get("GOOGLE_API_KEY")
    or ""
)

# ==========================================
# MATRIKS VIBE & PROMPT THREADS
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

# CTA untuk Model 1 (Link langsung di post utama - 1 Post)
DIRECT_CTA_TEMPLATES = [
    "Belinya disini yaa 👇\n🔗 {link}",
    "Spill lapak aslinya di sini yaa:\n🔗 {link}",
    "Beli yang ori langsung di sini biar gak zonk:\n🔗 {link}",
    "Buat yang mau samaan langsung ambil di sini:\n🔗 {link}",
    "Mumpung lagi promo, cek langsung di sini ya:\n🔗 {link}",
    "Yang butuh solusinya juga, link toko resminya di sini:\n🔗 {link}"
]

# CTA pembuka untuk Model 2 (Link di kolom balasan - 2 Post)
FALLBACK_CTA_STARTERS = [
    "Awas dapet tiruan yang gampang rusak/tumpul ya, link official store yang beneran ori di sini:",
    "Biar gak capek nyari manual ketumpuk seller abal-abal, ambil di lapak aslinya di sini:",
    "Sumpah harganya gak masuk akal murahnya wkwk, cek sendiri di sini mumpung diskon:",
    "Buat yang males ribet dan butuh solusinya juga, link toko resminya aku taro sini ya:"
]

def sanitize_threads_text(text: str, max_chars: int = 495) -> str:
    if not text:
        return ""
    t = str(text).strip()

    # 1. Bersihkan label buatan AI: [Teks Utama], [Teks Balasan CTA], [Link], dll.
    t = re.sub(r'^\s*\[\s*(?:Teks\s+)?(?:Utama\vert{}Balasan\s+CTA\vert{}CTA\vert{}Postingan\vert{}Main\s+Post\vert{}Reply\s+CTA)\s*\]\s*:?\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'^\s*(?:Teks\s+Utama|Teks\s+Balasan\s+CTA|Balasan\s+CTA|CTA\s+Reply|Postingan\s+Utama)\s*:\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'\[\s*(?:Teks\s+)?(?:Utama\vert{}Balasan\s+CTA\vert{}CTA\vert{}Postingan\vert{}Link)\s*\]', '', t, flags=re.IGNORECASE)
    t = t.replace("---REPLY_CTA---", "").strip()

    # 2. Hapus tanda kutip pembungkus di awal & akhir jika ada
    if len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'"))):
        t = t[1:-1].strip()

    # 3. Bersihkan awalan klise "POV:"
    t = re.sub(r'^\s*POV\s*:\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)

    # 4. Ubah sebutan TikTok 'keranjang kuning' & 'link di bio' menjadi istilah Threads/Shopee
    t = re.sub(r'keranjang\s+kuning(?:nya)?', 'link toko resminya', t, flags=re.IGNORECASE)
    t = re.sub(r'link\s+di\s+bio', 'link di bawah', t, flags=re.IGNORECASE)

    t = t.strip()
    if len(t) > max_chars:
        return t[:max_chars - 3].rstrip() + "..."
    return t

# Cache daftar model agar list_models hanya dipanggil 1 kali per eksekusi
CACHED_GEMINI_PAIRS = None

def get_gemini_pairs(key: str):
    global CACHED_GEMINI_PAIRS
    if CACHED_GEMINI_PAIRS is not None:
        return CACHED_GEMINI_PAIRS

    available = []
    for ver in ["v1", "v1beta"]:
        list_url = f"https://generativelanguage.googleapis.com/{ver}/models?key={key}"
        try:
            r = requests.get(list_url, timeout=10).json()
            if "models" in r:
                for m in r["models"]:
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        available.append((ver, m["name"].replace("models/", "")))
        except Exception:
            pass

    preferred = ["1.5-flash", "2.0-flash", "flash", "1.5-pro", "gemini-pro"]
    def get_rank(pair):
        v, n = pair
        for idx, pref in enumerate(preferred):
            if pref in n.lower():
                return idx
        return 99

    available.sort(key=get_rank)
    if available:
        CACHED_GEMINI_PAIRS = available
        return available

    fallback = [
        ("v1", "gemini-1.5-flash"),
        ("v1", "gemini-1.5-pro"),
        ("v1beta", "gemini-1.5-flash"),
        ("v1beta", "gemini-2.0-flash"),
    ]
    CACHED_GEMINI_PAIRS = fallback
    return fallback

def call_gemini(prompt: str) -> str:
    key = str(AI_API_KEY).strip().replace("'", "").replace('"', "") if AI_API_KEY else ""
    if not key:
        raise Exception("API Key Gemini (AI_API_KEY) tidak ditemukan!")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.95,
            "topP": 0.95,
            "topK": 40
        }
    }

    pairs = get_gemini_pairs(key)
    for ver, m_name in pairs:
        url = f"https://generativelanguage.googleapis.com/{ver}/models/{m_name}:generateContent?key={key}"
        try:
            res = requests.post(url, json=payload, timeout=25).json()
            if "candidates" in res and res["candidates"]:
                text_out = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_out:
                    return text_out
            elif "error" in res:
                err_msg = res["error"].get("message", "")
                print(f"[GEMINI REJECTED] {m_name}: {err_msg}")
                if res["error"].get("code") == 429:
                    time.sleep(4)
        except Exception as e:
            print(f"[GEMINI RETRY] {e}")

    raise Exception("Panggilan Gemini gagal pada seluruh model yang tersedia!")

def parse_time_str(t_str: str) -> int:
    t_clean = str(t_str).strip()
    parts = re.findall(r'\d+', t_clean)
    if len(parts) >= 2:
        h, m = int(parts[0]), int(parts[1])
        if h >= 24 or (h == 0 and m == 0):
            return 23 * 60 + 45
        return h * 60 + m
    return 4 * 60 + 30

def generate_slots(total_count, start_time_str="04:30", end_time_str="23:45"):
    if total_count <= 0:
        return []
    if total_count == 1:
        return [start_time_str]
    start_m = parse_time_str(start_time_str)
    end_m = parse_time_str(end_time_str)
    if end_m <= start_m:
        end_m = 23 * 60 + 45

    step = (end_m - start_m) / (total_count - 1)
    slots = []
    for i in range(total_count):
        curr_m = 5 * round(int(round(start_m + i * step)) / 5)
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

def get_sheets_client():
    raw_creds = str(GCP_CREDS_BASE64).strip() if GCP_CREDS_BASE64 else ""
    if not raw_creds:
        raise Exception("GCP_CREDS_BASE64 belum disetel!")
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

def open_target_spreadsheet(client):
    if SPREADSHEET_ID:
        return client.open_by_key(SPREADSHEET_ID)
    return client.open("TAB")

# ==========================================
# MODUL ANALITIK & AI ENGAGEMENT ENGINE
# ==========================================
def update_threads_insights(sh, accounts_map):
    """Memperbarui metrik views, likes, replies, reposts pada 35 baris POSTED terbaru."""
    data_ws = sh.worksheet("data")
    rows = data_ws.get_all_values()
    if len(rows) <= 1:
        return

    now_dt = datetime.now(TZ)
    updated_count = 0
    start_scan_idx = max(2, len(rows) - 35)

    for idx in range(start_scan_idx, len(rows) + 1):
        r = rows[idx - 1]
        while len(r) < 17:
            r.append("")

        if r[7].strip().upper() != "POSTED":
            continue

        raw_candidates = [r[8].strip(), r[9].strip()]
        main_id = ""
        detected_acc = r[2].strip()

        for cand in raw_candidates:
            if not cand:
                continue
            if ":" in cand:
                parts = cand.split(":", 1)
                detected_acc = parts[0].strip()
                cand = parts[1].strip()

            m_id = re.search(r'\b\d{15,20}\b', cand)
            if m_id:
                main_id = m_id.group(0)
                break

        if not main_id:
            continue

        acc_info = accounts_map.get(detected_acc) or accounts_map.get(r[2].strip()) or (list(accounts_map.values())[0] if accounts_map else None)
        if not acc_info:
            continue

        tok = acc_info["access_token"]
        ins_url = f"https://graph.threads.net/v1.0/{main_id}/insights?metric=views,likes,replies,reposts&access_token={tok}"

        try:
            res = requests.get(ins_url, timeout=6).json()
            if "data" in res:
                metrics_data = {item["name"]: item["values"][0]["value"] for item in res["data"] if "values" in item and item["values"]}
                update_vals = [[
                    metrics_data.get("views", 0),
                    metrics_data.get("likes", 0),
                    metrics_data.get("replies", 0),
                    metrics_data.get("reposts", 0),
                    now_dt.strftime("%Y-%m-%d %H:%M:%S")
                ]]
                try:
                    data_ws.update(range_name=f"M{idx}:Q{idx}", values=update_vals)
                except TypeError:
                    data_ws.update(f"M{idx}:Q{idx}", update_vals)
                updated_count += 1
        except Exception:
            pass

    if updated_count > 0:
        print(f"[INSIGHTS] Berhasil memperbarui metrik untuk {updated_count} postingan terbaru.")

def extract_self_learning_patterns(rows):
    """Mengekstrak copywriting terbaik dan produk dengan skor konversi tertinggi."""
    if len(rows) <= 1:
        return {"winning_copies": [], "winning_products": {}}

    posted_rows = []
    for r in rows[1:]:
        if len(r) >= 13 and str(r[7]).strip().upper() == "POSTED":
            try:
                v = float(r[12]) if len(r) > 12 and str(r[12]).strip().replace('.', '', 1).isdigit() else 0.0
                l = float(r[13]) if len(r) > 13 and str(r[13]).strip().replace('.', '', 1).isdigit() else 0.0
                rep = float(r[14]) if len(r) > 14 and str(r[14]).strip().replace('.', '', 1).isdigit() else 0.0
                repst = float(r[15]) if len(
