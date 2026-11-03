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
    "Belinya disini yaa 👇\n🛒 {link}",
    "Spill lapak aslinya di sini yaa:\n🛒 {link}",
    "Beli yang ori langsung di sini biar gak zonk:\n🛒 {link}",
    "Buat yang mau samaan langsung ambil di sini:\n🛒 {link}",
    "Mumpung lagi promo, cek langsung di sini ya:\n🛒 {link}",
    "Yang butuh solusinya juga, link toko resminya di sini:\n🛒 {link}"
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
    t = re.sub(r'^\s*\[\s*(?:Teks\s+)?(?:Utama|Balasan\s+CTA|CTA|Postingan|Main\s+Post|Reply\s+CTA)\s*\]\s*:?\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'^\s*(?:Teks\s+Utama|Teks\s+Balasan\s+CTA|Balasan\s+CTA|CTA\s+Reply|Postingan\s+Utama)\s*:\s*', '', t, flags=re.IGNORECASE | re.MULTILINE)
    t = re.sub(r'\[\s*(?:Teks\s+)?(?:Utama|Balasan\s+CTA|CTA|Postingan|Link)\s*\]', '', t, flags=re.IGNORECASE)
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
                repst = float(r[15]) if len(r) > 15 and str(r[15]).strip().replace('.', '', 1).isdigit() else 0.0
                score = v + (l * 5) + (rep * 8) + (repst * 10)
                posted_rows.append({
                    "text": str(r[3]).strip(),
                    "aff_link": str(r[6]).strip(),
                    "score": score
                })
            except Exception:
                pass

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

def calculate_model_engagement_ratio(rows):
    """Menganalisis performa historis Model 1 (link di post utama) vs Model 2 (link di reply)
    berdasarkan metrik engagement: views, likes, replies, reposts."""
    m1_scores = []
    m2_scores = []

    for r in rows[1:]:
        if len(r) >= 8 and str(r[7]).strip().upper() == "POSTED":
            try:
                v = float(r[12]) if len(r) > 12 and str(r[12]).strip().replace('.', '', 1).isdigit() else 0.0
                l = float(r[13]) if len(r) > 13 and str(r[13]).strip().replace('.', '', 1).isdigit() else 0.0
                rep = float(r[14]) if len(r) > 14 and str(r[14]).strip().replace('.', '', 1).isdigit() else 0.0
                repst = float(r[15]) if len(r) > 15 and str(r[15]).strip().replace('.', '', 1).isdigit() else 0.0
                score = v + (l * 5) + (rep * 8) + (repst * 10)

                reply_val = str(r[5]).strip() if len(r) > 5 else ""
                if not reply_val or reply_val.lower() == "nan":
                    m1_scores.append(score)
                else:
                    m2_scores.append(score)
            except Exception:
                pass

    avg_m1 = sum(m1_scores) / len(m1_scores) if m1_scores else 0.0
    avg_m2 = sum(m2_scores) / len(m2_scores) if m2_scores else 0.0

    if avg_m1 == 0 and avg_m2 == 0:
        w_m1, w_m2 = 0.5, 0.5
    else:
        total = avg_m1 + avg_m2
        raw_m1 = (avg_m1 / total) if total > 0 else 0.5
        # Multi-armed bandit: alokasi proporsional dengan batas eksplorasi 20% - 80%
        w_m1 = max(0.20, min(0.80, raw_m1))
        w_m2 = 1.0 - w_m1

    return {
        "avg_m1": avg_m1,
        "avg_m2": avg_m2,
        "weight_m1": w_m1,
        "weight_m2": w_m2
    }

def decide_post_model_by_ai(slot_time: str, model_weights: dict) -> bool:
    """Menentukan secara dinamis apakah post menggunakan:
    - True  = Model 1 (Direct: Link di post utama, 1 post saja)
    - False = Model 2 (2 Posts: Hook di utama, Link di kolom reply)"""
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

# ==========================================
# PEMBUATAN DRAF OTOMATIS (AI ENGAGEMENT DECISION)
# ==========================================
def auto_generate_today_drafts_if_needed(sh, accounts_map):
    now_dt = datetime.now(TZ)
    today_str = now_dt.strftime("%Y-%m-%d")

    data_ws = sh.worksheet("data")
    existing_rows = data_ws.get_all_values()

    active_accounts = list(accounts_map.keys())
    if not active_accounts:
        print("[AUTO-GEN] Tab Accounts kosong!")
        return

    cfg_ws = sh.worksheet("Config")
    cfg_rows = cfg_ws.get_all_values()
    cfg_data = {str(r[0]).strip(): str(r[1]).strip() for r in cfg_rows if len(r) >= 2 and str(r[0]).strip()}

    try:
        start_str = cfg_data.get("start_datetime", "2026-01-01 04:30").replace("'", "")
        end_str = cfg_data.get("end_datetime", "2026-12-31 23:45").replace("'", "")
        start_date = datetime.strptime(start_str.split()[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str.split()[0], "%Y-%m-%d").date()
        if not (start_date <= now_dt.date() <= end_date):
            print(f"[AUTO-GEN] Hari ini ({today_str}) di luar rentang aktif Config. Lewati.")
            return
    except Exception:
        pass

    try:
        daily_viral = int(cfg_data.get("daily_viral_count", cfg_data.get("count_viral", 0)))
        daily_text = int(cfg_data.get("daily_text_count", cfg_data.get("count_aff_text", 0)))
        daily_video = int(cfg_data.get("daily_video_count", cfg_data.get("count_aff_media", 25)))
    except Exception:
        daily_viral, daily_text, daily_video = 0, 0, 25

    posts_per_account = daily_viral + daily_text + daily_video
    if posts_per_account <= 0:
        posts_per_account = 25
        daily_video = 25
    posts_per_account = min(posts_per_account, 50)

    # Analisis Engagement & Self-Learning
    model_stats = calculate_model_engagement_ratio(existing_rows)
    learnings = extract_self_learning_patterns(existing_rows)
    winning_copies = learnings["winning_copies"]
    winning_products_map = learnings["winning_products"]

    winning_context_prompt = ""
    if winning_copies:
        formatted_examples = "\n---\n".join(winning_copies[:2])
        winning_context_prompt = (
            f"\n[REFERENSI GAYA TULISAN ENGAGEMENT TERTINGGI]:\n{formatted_examples}\n"
            f"(Tirulah ritme santainya tanpa menyalin kata per kata)\n"
        )

    print(f"[AI ENGAGEMENT ENGINE] Skor Rata-rata Model 1: {model_stats['avg_m1']:.1f} | Model 2: {model_stats['avg_m2']:.1f}")
    print(f"[AI ENGAGEMENT ENGINE] Probabilitas Dinamis: Model 1 = {model_stats['weight_m1']*100:.1f}%, Model 2 = {model_stats['weight_m2']*100:.1f}%")

    # Hitung postingan hari ini per akun
    account_today_counts = {}
    if len(existing_rows) > 1:
        for r in existing_rows[1:]:
            if len(r) >= 3 and str(r[0]).strip() == today_str:
                acc_name_row = str(r[2]).strip()
                account_today_counts[acc_name_row] = account_today_counts.get(acc_name_row, 0) + 1

    target_cfg_acc = cfg_data.get("target_autopilot_account", "-- Semua Akun (All Accounts) --").strip()
    if target_cfg_acc != "-- Semua Akun (All Accounts) --" and target_cfg_acc in active_accounts:
        candidate_accounts = [target_cfg_acc]
    else:
        candidate_accounts = active_accounts

    accounts_to_generate = [acc for acc in candidate_accounts if account_today_counts.get(acc, 0) < posts_per_account]

    if not accounts_to_generate:
        print(f"[AUTO-GEN] Semua akun sudah memiliki draf lengkap ({posts_per_account} post) untuk {today_str}.")
        return

    cfg_start_clock = cfg_data.get("start_time", "04:30")
    now_minutes = now_dt.hour * 60 + now_dt.minute
    cfg_start_minutes = parse_time_str(cfg_start_clock)

    if now_minutes > 23 * 60 + 20:
        print("[AUTO-GEN] Waktu sudah melewati 23:20 WIB, pembuatan draf ditunda ke pergantian hari.")
        return

    if now_minutes > cfg_start_minutes:
        base_start_m = now_minutes + 5
    else:
        base_start_m = cfg_start_minutes

    end_clock = cfg_data.get("end_time", "23:45")

    prod_ws = sh.worksheet("Products")
    all_prods = prod_ws.get_all_records()
    ready_prods = [p for p in all_prods if str(p.get("status", "")).strip().upper() == "READY"]

    if not ready_prods:
        print("[AUTO-GEN] Tab Products tidak memiliki produk READY.")
        return

    prods_with_media = [p for p in ready_prods if str(p.get("media_url", "")).strip()]
    prods_text_only = [p for p in ready_prods if not str(p.get("media_url", "")).strip()] or ready_prods

    def pick_weighted_product(prod_list):
        if not prod_list:
            return random.choice(ready_prods)
        weights = []
        for p in prod_list:
            link = str(p.get("affiliate_link", "")).strip()
            sc = winning_products_map.get(link, None)
            if sc is None:
                w = 3.5  # Prioritas eksplorasi produk baru
            elif sc == 0:
                w = 1.2
            else:
                w = 1.0 + min(sc / 150.0, 6.0)
            weights.append(w)
        return random.choices(prod_list, weights=weights, k=1)[0]

    full_types_template = arrange_post_types_3way(daily_viral, daily_text, daily_video)

    for acc_idx, acc_name in enumerate(accounts_to_generate):
        existing_cnt = account_today_counts.get(acc_name, 0)
        rem_count = posts_per_account - existing_cnt
        if rem_count <= 0:
            continue

        print(f"[AUTO-GEN] Meracik {rem_count} post untuk @{acc_name} (Sudah ada: {existing_cnt}/{posts_per_account})...")
        acc_start_m = min(base_start_m + (acc_idx * 2), 23 * 60 + 30)
        staggered_start = f"{acc_start_m // 60:02d}:{acc_start_m % 60:02d}"

        slots = generate_slots(rem_count, start_time_str=staggered_start, end_time_str=end_clock)
        types_list = full_types_template[:rem_count]

        acc_rows = []
        for slot_time, p_type in zip(slots, types_list):
            vibe = random.choice(THREADS_VIBES)
            direct_to_main = decide_post_model_by_ai(slot_time, model_stats)

            if p_type == "viral":
                topik = random.choice(VIRAL_OBSERVATIONS)
                prompt_v = (
                    f"Kamu adalah user Threads Indonesia yang santai dan relate.\n"
                    f"Tulis 1 postingan tentang: '{topik}'. Vibe: {vibe}.\n{winning_context_prompt}"
                    f"DILARANG pakai kata 'POV:' atau label apapun. Langsung tulis kalimat pembuka. Maksimal 220 karakter tanpa tanda kutip."
                )
                p_text = call_gemini(prompt_v)
                clean_p_text = sanitize_threads_text(p_text)
                acc_rows.append([today_str, slot_time, acc_name, clean_p_text, "", "", "", "PENDING", "", "", "", ""])

            elif p_type == "video":
                p_cur = pick_weighted_product(prods_with_media if prods_with_media else ready_prods)

                if direct_to_main:
                    # Model 1: Link langsung di post utama (1 post saja, reply kosong)
                    prompt = (
                        f"Kamu adalah user Threads Indonesia yang santai, jujur, dan relate.\n"
                        f"Tulis 1 postingan pengantar video untuk produk: {p_cur['product_name']}.\n"
                        f"Highlight: {p_cur.get('highlight', '')}. Vibe: {vibe}.\n{winning_context_prompt}\n"
                        f"ATURAN:\n"
                        f"1. DILARANG pakai kata 'POV:', '[Teks Utama]', atau bahasa iklan kaku. Langsung ceritakan masalah nyata sehari-hari.\n"
                        f"2. JANGAN taruh link di dalam teks buatanmu (link toko akan ditempel otomatis di bawah).\n"
                        f"3. Maksimal 230 karakter tanpa tanda kutip."
                    )
                    raw_out = call_gemini(prompt)
                    clean_main_txt = sanitize_threads_text(raw_out)
                    cta_direct = random.choice(DIRECT_CTA_TEMPLATES).format(link=p_cur['affiliate_link'])
                    full_main_post = f"{clean_main_txt}\n\n{cta_direct}"

                    media_formatted = prepare_media_for_post(str(p_cur.get("media_url", "")).strip(), duplicate_single_video=True)
                    acc_rows.append([today_str, slot_time, acc_name, full_main_post, media_formatted, "", p_cur['affiliate_link'], "PENDING", "", "", "", ""])

                else:
                    # Model 2: Hook di post utama, Link di Reply
                    prompt = (
                        f"Kamu adalah user Threads Indonesia yang santai, jujur, dan relate.\n"
                        f"Tulis postingan pengantar video untuk produk: {p_cur['product_name']}.\n"
                        f"Highlight: {p_cur.get('highlight', '')}. Vibe: {vibe}.\n{winning_context_prompt}\n"
                        f"ATURAN POSTINGAN UTAMA:\n"
                        f"1. DILARANG menggunakan kata 'POV:', '[Teks Utama]', atau bahasa iklan kaku. Langsung mulai dari masalah nyata sehari-hari.\n"
                        f"2. JANGAN taruh link atau sebutan 'keranjang kuning'/'link bio'. Maksimal 290 karakter.\n\n"
                        f"ATURAN BALASAN CTA:\n"
                        f"1. Tulis 1 kalimat singkat penarik klik lapak Shopee (anti-zonk, cari lapak original, atau heran harganya murah). DILARANG pakai '[Teks Balasan CTA]'. Maksimal 110 karakter.\n\n"
                        f"PENTING: Pisahkan HANYA dengan tanda pembatas '---REPLY_CTA---' tanpa label tambahan apapun!"
                    )
                    raw_out = call_gemini(prompt)
                    if "---REPLY_CTA---" in raw_out:
                        parts = raw_out.split("---REPLY_CTA---", 1)
                        main_txt, cta_txt = parts[0].strip(), parts[1].strip()
                    else:
                        main_txt, cta_txt = raw_out.strip(), random.choice(FALLBACK_CTA_STARTERS)

                    clean_main_txt = sanitize_threads_text(main_txt)
                    clean_cta_txt = sanitize_threads_text(cta_txt)
                    aff_reply = f"{clean_cta_txt}\n{p_cur['affiliate_link']}"
                    media_formatted = prepare_media_for_post(str(p_cur.get("media_url", "")).strip(), duplicate_single_video=True)
                    acc_rows.append([today_str, slot_time, acc_name, clean_main_txt, media_formatted, aff_reply, p_cur['affiliate_link'], "PENDING", "", "", "", ""])

            else:
                p_cur = pick_weighted_product(prods_text_only)
                if direct_to_main:
                    prompt = (
                        f"Tulis 1 postingan teks Threads tentang produk: {p_cur['product_name']}.\n"
                        f"Keunggulan: {p_cur.get('highlight', '')}. Vibe: {vibe}.\n{winning_context_prompt}"
                        f"DILARANG pakai label '[Teks Utama]' atau 'POV:'. Maksimal 230 karakter."
                    )
                    raw_out = call_gemini(prompt)
                    clean_main_txt = sanitize_threads_text(raw_out)
                    cta_direct = random.choice(DIRECT_CTA_TEMPLATES).format(link=p_cur['affiliate_link'])
                    full_main_post = f"{clean_main_txt}\n\n{cta_direct}"
                    acc_rows.append([today_str, slot_time, acc_name, full_main_post, "", "", p_cur['affiliate_link'], "PENDING", "", "", "", ""])
                else:
                    prompt = (
                        f"Tulis postingan teks Threads tentang produk: {p_cur['product_name']}.\n"
                        f"Keunggulan: {p_cur.get('highlight', '')}. Vibe: {vibe}.\n{winning_context_prompt}"
                        f"DILARANG pakai label '[Teks Utama]' atau 'POV:'.\n"
                        f"PISAHKAN HANYA DENGAN '---REPLY_CTA---' diikuti 1 kalimat balasan CTA singkat."
                    )
                    raw_out = call_gemini(prompt)
                    if "---REPLY_CTA---" in raw_out:
                        parts = raw_out.split("---REPLY_CTA---", 1)
                        main_txt, cta_txt = parts[0].strip(), parts[1].strip()
                    else:
                        main_txt, cta_txt = raw_out.strip(), random.choice(FALLBACK_CTA_STARTERS)

                    clean_main_txt = sanitize_threads_text(main_txt)
                    clean_cta_txt = sanitize_threads_text(cta_txt)
                    aff_reply = f"{clean_cta_txt}\n{p_cur['affiliate_link']}"
                    acc_rows.append([today_str, slot_time, acc_name, clean_main_txt, "", aff_reply, p_cur['affiliate_link'], "PENDING", "", "", "", ""])

            time.sleep(1)

        if acc_rows:
            try:
                data_ws.append_rows(acc_rows)
                print(f"[AUTO-GEN] Berhasil menyimpan {len(acc_rows)} baris untuk @{acc_name}!")
            except Exception as e_app:
                print(f"[WARN] append_rows gagal ({e_app}), menyimpan baris per baris...")
                for r_item in acc_rows:
                    data_ws.append_row(r_item)
                    time.sleep(0.3)

# ==========================================
# MODUL PUBLIKASI KE THREADS API
# ==========================================
def wait_for_container(container_id: str, access_token: str, max_wait: int = 90) -> bool:
    url = f"https://graph.threads.net/v1.0/{container_id}?fields=status,error_message&access_token={access_token}"
    start = time.time()
    time.sleep(2)
    while time.time() - start < max_wait:
        try:
            res = requests.get(url, timeout=10).json()
            status = res.get("status")
            if status == "FINISHED":
                return True
            if status == "ERROR":
                return False
        except Exception:
            pass
        time.sleep(3)
    return False

def create_single_media_container(user_id: str, access_token: str, media_url: str, text: str = "", is_carousel_item: bool = False, reply_to_id: str = "") -> str:
    is_video = any(media_url.lower().endswith(ext) for ext in [".mp4", ".mov", ".m4v"]) or "/video/upload/" in media_url
    endpoint = f"https://graph.threads.net/v1.0/{user_id}/threads"
    params = {
        "media_type": "VIDEO" if is_video else "IMAGE",
        "access_token": access_token
    }
    if is_video:
        params["video_url"] = media_url
    else:
        params["image_url"] = media_url

    if is_carousel_item:
        params["is_carousel_item"] = "true"
    else:
        if text:
            params["text"] = sanitize_threads_text(text)
        if reply_to_id:
            params["reply_to_id"] = reply_to_id

    res = requests.post(endpoint, data=params, timeout=25).json()
    if "id" not in res:
        raise Exception(f"Gagal container: {res}")
    return res["id"]

def publish_threads_post(user_id: str, access_token: str, text: str, media_raw: str = "", reply_to_id: str = "") -> str:
    text = sanitize_threads_text(text)
    media_list = [m.strip() for m in str(media_raw).split(",") if m.strip()]

    if len(media_list) > 1:
        child_ids = []
        for m_url in media_list:
            c_id = create_single_media_container(user_id, access_token, m_url, is_carousel_item=True)
            if not wait_for_container(c_id, access_token):
                raise Exception("Carousel item gagal diproses")
            child_ids.append(c_id)

        car_params = {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "text": text,
            "access_token": access_token
        }
        if reply_to_id:
            car_params["reply_to_id"] = reply_to_id

        car_res = requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads", data=car_params, timeout=25).json()
        container_id = car_res.get("id")
        if not container_id or not wait_for_container(container_id, access_token):
            raise Exception("Carousel container gagal diproses")

    elif len(media_list) == 1:
        container_id = create_single_media_container(user_id, access_token, media_list[0], text=text, reply_to_id=reply_to_id)
        if not wait_for_container(container_id, access_token):
            raise Exception("Media container gagal diproses")
    else:
        text_params = {
            "media_type": "TEXT",
            "text": text,
            "access_token": access_token
        }
        if reply_to_id:
            text_params["reply_to_id"] = reply_to_id
        res = requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads", data=text_params, timeout=20).json()
        container_id = res.get("id")
        time.sleep(2)

    pub_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
    for _ in range(4):
        time.sleep(2)
        r = requests.post(pub_url, data={"creation_id": container_id, "access_token": access_token}, timeout=25).json()
        if "id" in r:
            return r["id"]
        time.sleep(3)

    raise Exception("Gagal publish ke Threads")

# ==========================================
# RUNNER UTAMA
# ==========================================
def run_worker():
    print(f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} WIB] Memeriksa jadwal antrean...")
    client = get_sheets_client()
    sh = open_target_spreadsheet(client)

    acc_ws = sh.worksheet("Accounts")
    acc_records = acc_ws.get_all_records()
    accounts_map = {}
    for a in acc_records:
        name = str(a.get("name", "")).strip()
        uid = str(a.get("user_id", "")).strip()
        token = str(a.get("access_token", "")).strip()
        if name and uid and token:
            accounts_map[name] = {"user_id": uid, "access_token": token}

    try:
        update_threads_insights(sh, accounts_map)
    except Exception as e:
        print(f"[INSIGHTS WARN] {e}")

    try:
        auto_generate_today_drafts_if_needed(sh, accounts_map)
    except Exception as e:
        print(f"[AUTO-GEN ERROR] {e}")

    data_ws = sh.worksheet("data")
    rows = data_ws.get_all_values()
    if len(rows) <= 1:
        return

    now_dt = datetime.now(TZ)

    for idx, r in enumerate(rows[1:], start=2):
        while len(r) < 12:
            r.append("")

        post_date = r[0].strip()
        post_time = r[1].strip()
        target_acc = r[2].strip()
        main_text = r[3].strip()
        media_url = r[4].strip()
        reply_chain_text = r[5].strip()
        status = r[7].strip().upper()
        target_hijack_id = r[11].strip()

        if status != "PENDING" or not main_text:
            continue

        try:
            m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", post_date)
            t_m = re.match(r"^(\d{1,2}):(\d{1,2})", post_time)
            if not m or not t_m:
                continue
            p_dt = TZ.localize(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(t_m.group(1)), int(t_m.group(2))))
        except Exception:
            continue

        if p_dt > now_dt:
            continue

        acc_info = accounts_map.get(target_acc)
        if not acc_info:
            continue

        u_id = acc_info["user_id"]
        tok = acc_info["access_token"]

        data_ws.update_cell(idx, 8, "POSTING")
        print(f"[ROW {idx}] Sedang memproses @{target_acc}...")

        try:
            clean_main_post = sanitize_threads_text(main_text)
            main_id = publish_threads_post(u_id, tok, text=clean_main_post, media_raw=media_url, reply_to_id=target_hijack_id)

            current_parent = main_id
            # Jika baris adalah Model 1 (reply_chain_text kosong), balasan otomatis dilewati
            if reply_chain_text:
                replies = [rep.strip() for rep in reply_chain_text.split("---REPLY---") if rep.strip()]
                for rep_item in replies:
                    time.sleep(2)
                    safe_reply = sanitize_threads_text(rep_item)
                    current_parent = publish_threads_post(u_id, tok, text=safe_reply, media_raw="", reply_to_id=current_parent)

            # Batch update 1 kali panggilan agar hemat kuota write Google Sheets
            post_done_vals = [["POSTED", str(main_id), "", datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")]]
            try:
                data_ws.update(range_name=f"H{idx}:K{idx}", values=post_done_vals)
            except TypeError:
                data_ws.update(f"H{idx}:K{idx}", post_done_vals)

            print(f"[ROW {idx}] Sukses terbit: {main_id}")

        except Exception as ex:
            err_msg = str(ex)[:200]
            err_vals = [["ERROR", "", err_msg]]
            try:
                data_ws.update(range_name=f"H{idx}:J{idx}", values=err_vals)
            except TypeError:
                data_ws.update(f"H{idx}:J{idx}", err_vals)

if __name__ == "__main__":
    run_worker()
