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
# 🔐 PENGAMBILAN KREDENSIAL & SECRETS
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

SPREADSHEET_ID = get_secret("SPREADSHEET_ID", "12HI63liR64ugPz8IHQHy2gAhOOzSDMt0D0-YHO5x08E")
GCP_CREDS_BASE64 = get_secret("GCP_CREDS_BASE64")
AI_API_KEY = get_secret("AI_API_KEY")

# ==========================================
# 🧠 MATRIKS VIBE & PROMPT THREADS
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
    "Biar gak capek nyari manual ketumpuk seller abal-abal, ambil di lapak aslinya di sini:",
    "Sumpah harganya gak masuk akal murahnya wkwk, cek sendiri di sini mumpung diskon:",
    "Buat yang males ribet dan butuh solusinya juga, link toko resminya aku taro sini ya:"
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
        print("[GEMINI ERROR] AI_API_KEY kosong!")
        return "Salah satu barang yang lumayan ngebantu rutinitas harian."

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.95,
            "topP": 0.95,
            "topK": 40
        }
    }

    available_pairs = []
    for ver in ["v1", "v1beta"]:
        list_url = f"https://generativelanguage.googleapis.com/{ver}/models?key={key}"
        try:
            r = requests.get(list_url, timeout=10).json()
            if "models" in r:
                for m in r["models"]:
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        available_pairs.append((ver, m["name"].replace("models/", "")))
        except Exception:
            pass

    preferred = ["1.5-flash", "2.0-flash", "flash", "1.5-pro", "gemini-pro"]
    def get_rank(pair):
        v, n = pair
        for idx, pref in enumerate(preferred):
            if pref in n.lower():
                return idx
        return 99

    available_pairs.sort(key=get_rank)

    for ver, m_name in available_pairs:
        url = f"https://generativelanguage.googleapis.com/{ver}/models/{m_name}:generateContent?key={key}"
        try:
            res = requests.post(url, json=payload, timeout=30).json()
            if "candidates" in res and res["candidates"]:
                text_out = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_out:
                    return text_out
            elif "error" in res:
                print(f"[GEMINI REJECTED] {m_name}: {res['error'].get('message')}")
        except Exception as e:
            print(f"[GEMINI RETRY] {e}")

    fallback_models = [
        ("v1", "gemini-1.5-flash"),
        ("v1", "gemini-1.5-pro"),
        ("v1beta", "gemini-1.5-flash"),
        ("v1beta", "gemini-2.0-flash"),
    ]
    for ver, m_name in fallback_models:
        url = f"https://generativelanguage.googleapis.com/{ver}/models/{m_name}:generateContent?key={key}"
        try:
            res = requests.post(url, json=payload, timeout=30).json()
            if "candidates" in res and res["candidates"]:
                text_out = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_out:
                    return text_out
        except Exception:
            pass

    return "Salah satu barang yang lumayan ngebantu rutinitas harian."

def parse_time_str(t_str: str) -> int:
    t_clean = str(t_str).strip().replace(".", ":")
    if t_clean in ["24:00", "24.00", "00:00", "00.00"]:
        return 23 * 60 + 45
    m = re.match(r"^(\d{1,2}):(\d{1,2})", t_clean)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
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

# ==========================================
# 📊 MODUL ANALITIK & AI SELF-LEARNING
# ==========================================
def update_threads_insights(sh, accounts_map):
    data_ws = sh.worksheet("data")
    rows = data_ws.get_all_values()
    if len(rows) <= 1:
        return

    now_dt = datetime.now(TZ)
    updated_count = 0

    print(f"[{now_dt.strftime('%H:%M:%S')}] 🔍 Memeriksa postingan aktif untuk pembaruan metrik Threads...")

    for idx, r in enumerate(rows[1:], start=2):
        while len(r) < 17:
            r.append("")

        post_date = r[0].strip()
        post_time = r[1].strip()
        target_acc = r[2].strip()
        status = r[7].strip().upper()

        if status != "POSTED":
            continue

        raw_candidates = [r[8].strip(), r[9].strip()]
        main_id = ""
        detected_acc = target_acc

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

        try:
            m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", post_date)
            t_m = re.match(r"^(\d{1,2}):(\d{1,2})", post_time)
            if m and t_m:
                p_dt = TZ.localize(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(t_m.group(1)), int(t_m.group(2))))
                post_age_hours = (now_dt - p_dt).total_seconds() / 3600.0
                if post_age_hours < 0.25 or post_age_hours > (14 * 24):
                    continue
        except Exception:
            pass

        acc_info = accounts_map.get(detected_acc)
        if not acc_info and target_acc != "ALL":
            acc_info = accounts_map.get(target_acc)
        if not acc_info and accounts_map:
            acc_info = list(accounts_map.values())[0]

        if not acc_info:
            continue

        tok = acc_info["access_token"]
        ins_url = f"https://graph.threads.net/v1.0/{main_id}/insights?metric=views,likes,replies,reposts&access_token={tok}"

        try:
            res = requests.get(ins_url, timeout=15).json()
            if "data" in res:
                metrics_data = {item["name"]: item["values"][0]["value"] for item in res["data"] if "values" in item and item["values"]}
                v = metrics_data.get("views", 0)
                l = metrics_data.get("likes", 0)
                rep = metrics_data.get("replies", 0)
                repst = metrics_data.get("reposts", 0)

                update_vals = [[v, l, rep, repst, now_dt.strftime("%Y-%m-%d %H:%M:%S")]]
                try:
                    data_ws.update(range_name=f"M{idx}:Q{idx}", values=update_vals)
                except TypeError:
                    data_ws.update(f"M{idx}:Q{idx}", update_vals)

                updated_count += 1
                time.sleep(1)
            elif "error" in res:
                err_msg = res["error"].get("message", "")
                print(f"[INSIGHTS WARN] Meta menolak post {main_id}: {err_msg}")
        except Exception as ex:
            print(f"[INSIGHTS WARN] Gagal menarik metrik post {main_id}: {ex}")

    if updated_count > 0:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] 📈 Sukses memperbarui metrik untuk {updated_count} postingan!")

def extract_self_learning_patterns(rows):
    if len(rows) <= 1:
        return {"winning_copies": [], "winning_products": {}, "top_hour_slots": []}

    posted_rows = []
    for r in rows[1:]:
        if len(r) >= 13 and r[7].strip().upper() == "POSTED":
            try:
                views_cnt = int(r[12].strip()) if r[12].strip().isdigit() else 0
                likes_cnt = int(r[13].strip()) if len(r) > 13 and r[13].strip().isdigit() else 0
                posted_rows.append({
                    "date": r[0].strip(),
                    "time": r[1].strip(),
                    "text": r[3].strip(),
                    "aff_link": r[6].strip(),
                    "views": views_cnt,
                    "likes": likes_cnt
                })
            except Exception:
                pass

    if not posted_rows:
        return {"winning_copies": [], "winning_products": {}, "top_hour_slots": []}

    # 1. Winning Copies: 3 post dengan views terbanyak
    sorted_by_views = sorted(posted_rows, key=lambda x: x["views"], reverse=True)
    top_copies = [x["text"] for x in sorted_by_views[:3] if x["views"] > 0]

    # 2. Winning Products
    product_views = {}
    for x in posted_rows:
        link = x["aff_link"]
        if link:
            product_views[link] = product_views.get(link, 0) + x["views"]

    # 3. Peak Hours
    hour_views = {}
    hour_counts = {}
    for x in posted_rows:
        try:
            h = int(x["time"].split(":")[0])
            hour_views[h] = hour_views.get(h, 0) + x["views"]
            hour_counts[h] = hour_counts.get(h, 0) + 1
        except Exception:
            pass

    top_hours = []
    if hour_counts:
        avg_hour = {h: hour_views[h] / hour_counts[h] for h in hour_views if hour_counts[h] > 0}
        sorted_hours = sorted(avg_hour.items(), key=lambda item: item[1], reverse=True)
        top_hours = [item[0] for item in sorted_hours if item[1] > 0]

    return {
        "winning_copies": top_copies,
        "winning_products": product_views,
        "top_hour_slots": top_hours
    }

# ==========================================
# ⚙️ PEMBUATAN DRAF OTOMATIS (MULTI-AKUN DINAMIS)
# ==========================================
def auto_generate_today_drafts_if_needed(sh, accounts_map):
    now_dt = datetime.now(TZ)
    today_str = now_dt.strftime("%Y-%m-%d")

    data_ws = sh.worksheet("data")
    existing_rows = data_ws.get_all_values()

    today_rows_count = 0
    if len(existing_rows) > 1:
        for r in existing_rows[1:]:
            if len(r) > 0 and r[0].strip() == today_str:
                today_rows_count += 1

    if today_rows_count > 0:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] ℹ️ Draf tanggal {today_str} sudah ada ({today_rows_count} baris di sheet). Pembuatan draf baru dilewati.")
        return

    # 1. BACA DINAMIS SEMUA AKUN DARI TAB ACCOUNTS
    active_accounts = list(accounts_map.keys())
    if not active_accounts:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] ⚠️ Tab Accounts kosong! Daftarkan akun terlebih dahulu.")
        return

    # 2. BACA DINAMIS ANGKA DARI CONFIG (YANG DI-SET DARI STREAMLIT)
    cfg_ws = sh.worksheet("Config")
    cfg_rows = cfg_ws.get_all_values()
    cfg_data = {r[0].strip(): r[1].strip() for r in cfg_rows if len(r) >= 2 and r[0].strip()}

    try:
        start_str = cfg_data.get("start_datetime", "2026-01-01 04:30").replace("'", "")
        end_str = cfg_data.get("end_datetime", "2026-12-31 23:45").replace("'", "")
        start_date = datetime.strptime(start_str.split()[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str.split()[0], "%Y-%m-%d").date()
        if not (start_date <= now_dt.date() <= end_date):
            print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] ⚠️ Hari ini di luar rentang aktif Config. Lewati.")
            return
    except Exception as e:
        print(f"[AUTO-GEN WARN] Gagal cek tanggal: {e}")

    try:
        daily_viral = int(cfg_data.get("daily_viral_count", cfg_data.get("count_viral", 0)))
        daily_text = int(cfg_data.get("daily_text_count", cfg_data.get("count_aff_text", 0)))
        daily_video = int(cfg_data.get("daily_video_count", cfg_data.get("count_aff_media", 25)))
    except Exception:
        daily_viral, daily_text, daily_video = 0, 0, 25

    # Angka per akun dari Streamlit (bebas mau 25 atau 50)
    posts_per_account = daily_viral + daily_text + daily_video
    if posts_per_account <= 0:
        posts_per_account = 25
        daily_video = 25

    posts_per_account = min(posts_per_account, 50)

    start_clock = cfg_data.get("start_time", "04:30")
    end_clock = cfg_data.get("end_time", "23:45")

    total_semua_post = posts_per_account * len(active_accounts)
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] 📅 Menyusun Draf: {len(active_accounts)} Akun x {posts_per_account} Post = TOTAL {total_semua_post} POSTINGAN ({today_str})...")

    prod_ws = sh.worksheet("Products")
    all_prods = prod_ws.get_all_records()
    ready_prods = [p for p in all_prods if str(p.get("status", "")).strip().upper() == "READY"]

    if not ready_prods:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] ⚠️ Tab
