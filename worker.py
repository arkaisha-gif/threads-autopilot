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

SPREADSHEET_ID = get_secret("SPREADSHEET_ID", "12HI63liR64ugPz8IHQHy2gAhOOzSDMt0D0-YHO5x08E")
GCP_CREDS_BASE64 = get_secret("GCP_CREDS_BASE64")

# Deteksi multi-nama API Key agar tidak kosong di GitHub Actions
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
    key = str(AI_API_KEY).strip().replace("'", "").replace('"', "")
    if not key:
        raise Exception("API Key Gemini tidak ditemukan! Pastikan AI_API_KEY atau GEMINI_API_KEY terdaftar di Secrets.")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topP": 0.95,
            "topK": 40
        }
    }

    # Panggil v1 dan v1beta secara bergantian dengan model resmi
    target_urls = [
        f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={key}",
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
        f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={key}"
    ]

    last_err = ""
    for url in target_urls:
        try:
            res = requests.post(url, json=payload, timeout=20)
            res_json = res.json()
            if "candidates" in res_json and res_json["candidates"]:
                txt = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                if txt:
                    return txt
            elif "error" in res_json:
                last_err = res_json["error"].get("message", str(res_json))
        except Exception as e:
            last_err = str(e)
            continue

    raise Exception(f"Gemini API Gagal: {last_err}")

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
# MODUL ANALITIK (RINGAN)
# ==========================================
def update_threads_insights(sh, accounts_map):
    data_ws = sh.worksheet("data")
    rows = data_ws.get_all_values()
    if len(rows) <= 1:
        return

    now_dt = datetime.now(TZ)
    updated_count = 0
    start_scan_idx = max(2, len(rows) - 25)

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
            res = requests.get(ins_url, timeout=5).json()
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
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Sukses update metrik {updated_count} postingan!")

# ==========================================
# PEMBUATAN DRAF OTOMATIS (MULTI-AKUN AMAN)
# ==========================================
def auto_generate_today_drafts_if_needed(sh, accounts_map):
    now_dt = datetime.now(TZ)
    today_str = now_dt.strftime("%Y-%m-%d")

    data_ws = sh.worksheet("data")
    existing_rows = data_ws.get_all_values()

    active_accounts = list(accounts_map.keys())
    if not active_accounts:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Tab Accounts kosong!")
        return

    cfg_ws = sh.worksheet("Config")
    cfg_rows = cfg_ws.get_all_values()
    cfg_data = {r[0].strip(): r[1].strip() for r in cfg_rows if len(r) >= 2 and r[0].strip()}

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

    # Hitung postingan hari ini per akun
    account_today_counts = {}
    if len(existing_rows) > 1:
        for r in existing_rows[1:]:
            if len(r) >= 3 and r[0].strip() == today_str:
                acc_name_row = r[2].strip()
                account_today_counts[acc_name_row] = account_today_counts.get(acc_name_row, 0) + 1

    target_cfg_acc = cfg_data.get("target_autopilot_account", "-- Semua Akun (All Accounts) --").strip()
    if target_cfg_acc != "-- Semua Akun (All Accounts) --" and target_cfg_acc in active_accounts:
        candidate_accounts = [target_cfg_acc]
    else:
        candidate_accounts = active_accounts

    accounts_to_generate = [acc for acc in candidate_accounts if account_today_counts.get(acc, 0) < posts_per_account]

    if not accounts_to_generate:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Semua akun sudah memiliki draf lengkap untuk {today_str}.")
        return

    # JIKA SUDAH LEWAT DARI JAM 04:30 (MISAL DI-RUN SIANG), MULAI DARI JAM SEKARANG + 5 MENIT
    cfg_start_clock = cfg_data.get("start_time", "04:30")
    now_minutes = now_dt.hour * 60 + now_dt.minute
    cfg_start_minutes = parse_time_str(cfg_start_clock)

    if now_minutes > cfg_start_minutes:
        effective_start_m = now_minutes + 5
        start_clock = f"{effective_start_m // 60:02d}:{effective_start_m % 60:02d}"
    else:
        start_clock = cfg_start_clock

    end_clock = cfg_data.get("end_time", "23:45")

    prod_ws = sh.worksheet("Products")
    all_prods = prod_ws.get_all_records()
    ready_prods = [p for p in all_prods if str(p.get("status", "")).strip().upper() == "READY"]

    if not ready_prods:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Tab Products tidak memiliki produk berstatus READY.")
        return

    prods_with_media = [p for p in ready_prods if str(p.get("media_url", "")).strip()]
    prods_text_only = [p for p in ready_prods if not str(p.get("media_url", "")).strip()] or ready_prods

    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Menyiapkan draf AI untuk: {', '.join(accounts_to_generate)}...")

    new_rows = []

    for acc_idx, acc_name in enumerate(accounts_to_generate):
        start_h, start_m = map(int, start_clock.split(":"))
        offset_m = start_m + (acc_idx * 2)
        staggered_start = f"{start_h + (offset_m // 60):02d}:{offset_m % 60:02d}"

        slots = generate_slots(posts_per_account, start_time_str=staggered_start, end_time_str=end_clock)
        types_list = arrange_post_types_3way(daily_viral, daily_text, daily_video)

        for slot_time, p_type in zip(slots, types_list):
            vibe = random.choice(THREADS_VIBES)

            if p_type == "viral":
                topik = random.choice(VIRAL_OBSERVATIONS)
                prompt_v = (
                    f"Kamu adalah user Threads Indonesia yang santai dan relate.\n"
                    f"Tulis 1 postingan Threads tentang: '{topik}'. Vibe: {vibe}.\n"
                    f"Maksimal 220 karakter tanpa tanda kutip."
                )
                p_text = call_gemini(prompt_v)
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(p_text), "", "", "", "PENDING", "", "", "", ""])

            elif p_type == "video":
                p_cur = random.choice(prods_with_media if prods_with_media else ready_prods)
                prompt = (
                    f"Kamu adalah user Threads Indonesia.\n"
                    f"Tulis draf Threads pengantar video untuk produk: {p_cur['product_name']}.\n"
                    f"Highlight: {p_cur.get('highlight', '')}. Vibe: {vibe}.\n"
                    f"Bukan iklan, buat penonton sadar ini solusi praktis di Shopee. JANGAN taruh link di postingan utama. Maksimal 290 karakter.\n"
                    f"CTA Reply: 1 kalimat singkat pemicu klik Shopee (anti-zonk/keheranan harga murah), maks 110 karakter.\n"
                    f"FORMAT OUTPUT WAJIB:\n[Teks Utama]\n---REPLY_CTA---\n[Teks Balasan CTA]"
                )
                raw_out = call_gemini(prompt)
                if "---REPLY_CTA---" in raw_out:
                    parts = raw_out.split("---REPLY_CTA---", 1)
                    main_txt, cta_txt = parts[0].strip(), parts[1].strip()
                else:
                    main_txt, cta_txt = raw_out.strip(), random.choice(FALLBACK_CTA_STARTERS)

                aff_reply = f"{cta_txt}\n{p_cur['affiliate_link']}"
                media_formatted = prepare_media_for_post(str(p_cur.get("media_url", "")).strip(), duplicate_single_video=True)
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(main_txt), media_formatted, sanitize_threads_text(aff_reply), p_cur['affiliate_link'], "PENDING", "", "", "", ""])

            else:
                p_cur = random.choice(prods_text_only)
                prompt = (
                    f"Tulis postingan teks Threads tentang produk: {p_cur['product_name']}.\n"
                    f"Keunggulan: {p_cur.get('highlight', '')}. Vibe: {vibe}.\n"
                    f"FORMAT OUTPUT WAJIB:\n[Teks Utama]\n---REPLY_CTA---\n[Teks Balasan CTA]"
                )
                raw_out = call_gemini(prompt)
                if "---REPLY_CTA---" in raw_out:
                    parts = raw_out.split("---REPLY_CTA---", 1)
                    main_txt, cta_txt = parts[0].strip(), parts[1].strip()
                else:
                    main_txt, cta_txt = raw_out.strip(), random.choice(FALLBACK_CTA_STARTERS)

                aff_reply = f"{cta_txt}\n{p_cur['affiliate_link']}"
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(main_txt), "", sanitize_threads_text(aff_reply), p_cur['affiliate_link'], "PENDING", "", "", "", ""])

            time.sleep(1)

    new_rows.sort(key=lambda x: x[1])

    if new_rows:
        try:
            data_ws.append_rows(new_rows)
            print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] SUKSES! {len(new_rows)} postingan tersimpan rapi.")
        except Exception:
            for r_item in new_rows:
                data_ws.append_row(r_item)

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
        res = requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads", data=text_params, timeout=25).json()
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
    sh = client.open_by_key(SPREADSHEET_ID)

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
            main_id = publish_threads_post(u_id, tok, text=main_text, media_raw=media_url, reply_to_id=target_hijack_id)

            current_parent = main_id
            if reply_chain_text:
                replies = [rep.strip() for rep in reply_chain_text.split("---REPLY---") if rep.strip()]
                for rep_item in replies:
                    time.sleep(2)
                    safe_reply = sanitize_threads_text(rep_item)
                    current_parent = publish_threads_post(u_id, tok, text=safe_reply, media_raw="", reply_to_id=current_parent)

            data_ws.update_cell(idx, 8, "POSTED")
            data_ws.update_cell(idx, 9, main_id)
            data_ws.update_cell(idx, 10, "")
            data_ws.update_cell(idx, 11, datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"))
            print(f"[ROW {idx}] Berhasil terbit: {main_id}")

        except Exception as ex:
            err_msg = str(ex)[:200]
            data_ws.update_cell(idx, 8, "ERROR")
            data_ws.update_cell(idx, 10, err_msg)

if __name__ == "__main__":
    run_worker()
