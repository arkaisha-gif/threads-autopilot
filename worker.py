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

REPLY_STARTERS = [
    "Link tokonya gua taro sini ya biar gampang:",
    "Beli di official store resminya di sini mumpung diskon:",
    "Buat yang butuh juga, linknya di sini ya:",
    "Spill tokonya di sini guys:",
    "Link belinya yang ori ada di sini ya:",
    "Yang mau samaan langsung cek di sini:"
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

def generate_slots(total_count, start_time_str="04:30", end_time_str="23:30"):
    if total_count <= 0:
        return []
    if total_count == 1:
        return ["12:00"]
    h1, m1 = map(int, start_time_str.split(":"))
    h2, m2 = map(int, end_time_str.split(":"))
    start_minutes = h1 * 60 + m1
    end_minutes = h2 * 60 + m2
    step = (end_minutes - start_minutes) / (total_count - 1)
    slots = []
    for i in range(total_count):
        curr_m = 5 * round(int(round(start_minutes + i * step)) / 5)
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
    """Menarik metrik views, likes, replies, reposts dari Meta API untuk postingan yang berumur >= 12 jam."""
    data_ws = sh.worksheet("data")
    rows = data_ws.get_all_values()
    if len(rows) <= 1:
        return

    now_dt = datetime.now(TZ)
    updated_count = 0

    print(f"[{now_dt.strftime('%H:%M:%S')}] 🔍 Memeriksa postingan aktif untuk pembaruan metrik...")

    for idx, r in enumerate(rows[1:], start=2):
        while len(r) < 17:
            r.append("")

        post_date = r[0].strip()
        post_time = r[1].strip()
        target_acc = r[2].strip()
        status = r[7].strip().upper()
        main_id = r[8].strip()
        last_metric_update = r[16].strip()

        if status != "POSTED" or not main_id or not main_id.isdigit():
            continue

        try:
            m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", post_date)
            t_m = re.match(r"^(\d{1,2}):(\d{1,2})$", post_time)
            if not m or not t_m:
                continue
            p_dt = TZ.localize(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(t_m.group(1)), int(t_m.group(2))))
        except Exception:
            continue

        post_age_hours = (now_dt - p_dt).total_seconds() / 3600.0

        # Tarik metrik hanya untuk postingan usia antara 8 jam s/d 7 hari, dan belum dicek dalam 12 jam terakhir
        if post_age_hours < 8 or post_age_hours > (7 * 24):
            continue

        if last_metric_update:
            try:
                last_dt = TZ.localize(datetime.strptime(last_metric_update, "%Y-%m-%d %H:%M:%S"))
                if (now_dt - last_dt).total_seconds() / 3600.0 < 12:
                    continue
            except Exception:
                pass

        acc_info = accounts_map.get(target_acc)
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

                data_ws.update_cell(idx, 13, v)
                data_ws.update_cell(idx, 14, l)
                data_ws.update_cell(idx, 15, rep)
                data_ws.update_cell(idx, 16, repst)
                data_ws.update_cell(idx, 17, now_dt.strftime("%Y-%m-%d %H:%M:%S"))

                updated_count += 1
                time.sleep(1)  # Hindari rate limit Meta
        except Exception as ex:
            print(f"[INSIGHTS WARN] Gagal menarik metrik post {main_id}: {ex}")

    if updated_count > 0:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] 📈 Berhasil memperbarui metrik untuk {updated_count} postingan!")

def extract_self_learning_patterns(rows):
    """Menganalisa winning copies, winning products, dan jam tayang terbaik dari baris data."""
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
                    "acc": r[2].strip(),
                    "text": r[3].strip(),
                    "aff_link": r[6].strip(),
                    "views": views_cnt,
                    "likes": likes_cnt
                })
            except Exception:
                pass

    if not posted_rows:
        return {"winning_copies": [], "winning_products": {}, "top_hour_slots": []}

    # 1. Winning Copies: Ambil 3 postingan dengan views tertinggi
    sorted_by_views = sorted(posted_rows, key=lambda x: x["views"], reverse=True)
    top_copies = [x["text"] for x in sorted_by_views[:3] if x["views"] > 0]

    # 2. Winning Products: Akumulasi total views per link affiliate
    product_views = {}
    for x in posted_rows:
        link = x["aff_link"]
        if link:
            product_views[link] = product_views.get(link, 0) + x["views"]

    # 3. Best Performing Hours: Cari jam-jam dengan rata-rata impresi tertinggi
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

def auto_generate_today_drafts_if_needed(sh, accounts_map):
    now_dt = datetime.now(TZ)
    today_str = now_dt.strftime("%Y-%m-%d")

    data_ws = sh.worksheet("data")
    existing_rows = data_ws.get_all_values()

    has_today_posts = False
    if len(existing_rows) > 1:
        for r in existing_rows[1:]:
            if len(r) > 0 and r[0].strip() == today_str:
                has_today_posts = True
                break

    if has_today_posts:
        return

    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] 📅 Menyiapkan konten draf cerdas (AI Self-Learning) untuk ({today_str})...")

    # Ekstrak pola winning dari data historis
    learnings = extract_self_learning_patterns(existing_rows)
    winning_copies = learnings["winning_copies"]
    winning_products_map = learnings["winning_products"]
    top_hours = learnings["top_hour_slots"]

    cfg_ws = sh.worksheet("Config")
    cfg_rows = cfg_ws.get_all_values()
    cfg_data = {r[0].strip(): r[1].strip() for r in cfg_rows if len(r) >= 2 and r[0].strip()}

    try:
        start_str = cfg_data.get("start_datetime", "2026-01-01 00:00").replace("'", "")
        end_str = cfg_data.get("end_datetime", "2026-12-31 23:59").replace("'", "")
        start_date = datetime.strptime(start_str.split()[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str.split()[0], "%Y-%m-%d").date()
        if not (start_date <= now_dt.date() <= end_date):
            print(f"[AUTO-GEN] Hari ini di luar rentang aktif ({start_date} s/d {end_date}). Lewati.")
            return
    except Exception as e:
        print(f"[AUTO-GEN WARN] Gagal cek rentang tanggal: {e}")

    try:
        daily_viral = int(cfg_data.get("daily_viral_count", 2))
        daily_text = int(cfg_data.get("daily_text_count", 2))
        daily_video = int(cfg_data.get("daily_video_count", 4))
    except Exception:
        daily_viral, daily_text, daily_video = 2, 2, 4

    target_cfg_acc = cfg_data.get("target_autopilot_account", "-- Semua Akun (All Accounts) --")
    target_accounts = list(accounts_map.keys()) if target_cfg_acc == "-- Semua Akun (All Accounts) --" else [target_cfg_acc]

    prod_ws = sh.worksheet("Products")
    all_prods = prod_ws.get_all_records()
    ready_prods = [p for p in all_prods if str(p.get("status", "")).strip().upper() == "READY"]

    if not ready_prods:
        print("[AUTO-GEN] Tidak ada produk berstatus READY di tab Products.")
        return

    total_plan = daily_viral + daily_text + daily_video
    slots = generate_slots(total_plan, start_time_str="04:30", end_time_str="23:30")
    types_list = arrange_post_types_3way(daily_viral, daily_text, daily_video)

    # Susun referensi winning copy untuk prompt Gemini jika sudah tersedia data historis
    winning_context_prompt = ""
    if winning_copies:
        formatted_examples = "\n---\n".join(winning_copies)
        winning_context_prompt = (
            f"\n\n[CONTOH POSTINGAN TERBUKTI PALING BANYAK DISUKAI & DIRESPON DI AKUN INI]:\n"
            f"{formatted_examples}\n"
            f"Instruksi Khusus AI: Pelajari ritme tulisan, sudut pandang, dan cara penyampaian di atas. "
            f"Gunakan energi, vibe, dan struktur serupa untuk produk di bawah ini tanpa menjiplak teksnya secara kata per kata!"
        )

    new_rows = []
    for acc_name in target_accounts:
        acc_info = accounts_map.get(acc_name, {})
        acc_category = acc_info.get("category", "").strip().lower()

        # Filter produk berdasarkan niche akun
        if acc_category:
            matched_prods = [p for p in ready_prods if str(p.get("category", "")).strip().lower() == acc_category]
            active_prods = matched_prods if matched_prods else ready_prods
        else:
            active_prods = ready_prods

        # PEMILIHAN WINNING PRODUCT: Beri bobot probabilitas lebih tinggi pada produk yang punya views tinggi
        def pick_weighted_product(prod_list):
            if not prod_list:
                return random.choice(ready_prods)
            weights = []
            for p in prod_list:
                link = p.get("affiliate_link", "")
                vw = winning_products_map.get(link, 0)
                weights.append(1.0 + (vw / 200.0))  # Bobot dasar 1.0, meningkat seiring tingginya views
            return random.choices(prod_list, weights=weights, k=1)[0]

        prods_with_media = [p for p in active_prods if str(p.get("media_url", "")).strip()]
        prods_text_only = [p for p in active_prods if not str(p.get("media_url", "")).strip()] or active_prods

        for slot_time, p_type in zip(slots, types_list):
            vibe = random.choice(THREADS_VIBES)

            # Optimasi Jam Tayang: Jika slot ini masuk jam tayang terbukti ramai, prioritaskan format Video
            try:
                curr_hour = int(slot_time.split(":")[0])
                if top_hours and curr_hour in top_hours[:3] and prods_with_media:
                    p_type = "video"
            except Exception:
                pass

            if p_type == "viral":
                topik = random.choice(VIRAL_OBSERVATIONS)
                prompt_v = (
                    f"Kamu adalah user Threads Indonesia yang witty, cerdas, dan aktif.\n"
                    f"Tulis 1 postingan Threads yang memicu orang berkomentar atau repost tentang topik ini: '{topik}'.\n"
                    f"Vibe: {vibe}.\n{winning_context_prompt}\n\n"
                    f"Pedoman: Santai, huruf kecil atau punchline di awal, maksimal 220 karakter tanpa tanda kutip."
                )
                p_text = call_gemini(prompt_v)
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(p_text), "", "", "", "PENDING", "", "", "", ""])

            elif p_type == "video":
                p_cur = pick_weighted_product(prods_with_media) if prods_with_media else pick_weighted_product(active_prods)
                prompt = (
                    f"Kamu adalah pengguna Threads Indonesia yang aktif dan autentik.\n"
                    f"Tulis 1 postingan Threads pengantar video untuk produk ini:\n"
                    f"- Nama Produk: {p_cur['product_name']}\n"
                    f"- Keunggulan/Konteks: {p_cur.get('highlight', '')}\n"
                    f"- Vibe konten: {vibe}\n{winning_context_prompt}\n\n"
                    f"Aturan penting:\n"
                    f"1. BUKAN BAHASA SALES/IKLAN. Tulis seperti curhat nyata, review spontan, atau kebiasaan sehari-hari.\n"
                    f"2. Jangan gunakan template kaku ('MERTUA:', 'MAKASIH DOKTER'). Tulis mengalir alami.\n"
                    f"3. Jangan taruh link di postingan utama ini.\n"
                    f"4. Maksimal 300 karakter tanpa tanda kutip."
                )
                main_txt = call_gemini(prompt)
                closing = random.choice(REPLY_STARTERS)
                aff_reply = f"{closing}\n{p_cur['affiliate_link']}"
                media_formatted = prepare_media_for_post(str(p_cur.get("media_url", "")).strip(), duplicate_single_video=True)
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(main_txt), media_formatted, sanitize_threads_text(aff_reply), p_cur['affiliate_link'], "PENDING", "", "", "", ""])

            else:
                p_cur = pick_weighted_product(prods_text_only)
                prompt = (
                    f"Kamu adalah pengguna Threads Indonesia yang aktif dan santai.\n"
                    f"Tulis 1 postingan Threads teks tanpa gambar tentang produk/solusi praktis ini:\n"
                    f"- Produk: {p_cur['product_name']}\n"
                    f"- Keunggulan: {p_cur.get('highlight', '')}\n"
                    f"- Vibe: {vibe}\n{winning_context_prompt}\n\n"
                    f"Aturan penting:\n"
                    f"1. BUKAN BAHASA BROSUR. Tulis seperti tweet/Threads organik dari pengalaman pribadi.\n"
                    f"2. Gaya santai, mengalir, variatif, dan hindari kata klise jualan.\n"
                    f"3. Jangan taruh link di postingan utama.\n"
                    f"4. Maksimal 300 karakter tanpa tanda kutip."
                )
                main_txt = call_gemini(prompt)
                closing = random.choice(REPLY_STARTERS)
                aff_reply = f"{closing}\n{p_cur['affiliate_link']}"
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(main_txt), "", sanitize_threads_text(aff_reply), p_cur['affiliate_link'], "PENDING", "", "", "", ""])

    for row_item in new_rows:
        data_ws.append_row(row_item)

    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] ✅ Berhasil membuat {len(new_rows)} postingan dengan pola AI Self-Learning!")

def wait_for_container(container_id: str, access_token: str, max_wait: int = 150) -> bool:
    url = f"https://graph.threads.net/v1.0/{container_id}?fields=status,error_message&access_token={access_token}"
    start = time.time()
    time.sleep(3)
    while time.time() - start < max_wait:
        try:
            res = requests.get(url, timeout=15).json()
            status = res.get("status")
            if status == "FINISHED":
                return True
            if status == "ERROR":
                print(f"[CONTAINER ERROR] {res.get('error_message')}")
                return False
        except Exception as e:
            print(f"[POLL RETRY] {e}")
        time.sleep(4)
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

    res = requests.post(endpoint, data=params, timeout=30).json()
    if "id" not in res:
        raise Exception(f"Gagal buat media container: {res}")
    return res["id"]

def publish_threads_post(user_id: str, access_token: str, text: str, media_raw: str = "", reply_to_id: str = "") -> str:
    text = sanitize_threads_text(text)
    media_list = [m.strip() for m in str(media_raw).split(",") if m.strip()]
    container_id = ""

    if len(media_list) > 1:
        child_ids = []
        for m_url in media_list:
            c_id = create_single_media_container(user_id, access_token, m_url, is_carousel_item=True)
            if not wait_for_container(c_id, access_token):
                raise Exception(f"Media carousel item {c_id} belum siap diproses Meta")
            child_ids.append(c_id)

        car_params = {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "text": text,
            "access_token": access_token
        }
        if reply_to_id:
            car_params["reply_to_id"] = reply_to_id

        car_res = requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads", data=car_params, timeout=30).json()
        if "id" not in car_res:
            raise Exception(f"Gagal buat container carousel: {car_res}")
        container_id = car_res["id"]

        if not wait_for_container(container_id, access_token):
            raise Exception(f"Container carousel {container_id} belum siap (status != FINISHED)")

    elif len(media_list) == 1:
        m_url = media_list[0]
        container_id = create_single_media_container(user_id, access_token, m_url, text=text, reply_to_id=reply_to_id)
        if not wait_for_container(container_id, access_token):
            raise Exception(f"Container media {container_id} belum siap (status != FINISHED)")
    else:
        text_params = {
            "media_type": "TEXT",
            "text": text,
            "access_token": access_token
        }
        if reply_to_id:
            text_params["reply_to_id"] = reply_to_id
        res = requests.post(f"https://graph.threads.net/v1.0/{user_id}/threads", data=text_params, timeout=30).json()
        if "id" not in res:
            raise Exception(f"Gagal buat text container: {res}")
        container_id = res["id"]
        time.sleep(2)

    pub_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
    pub_res = {}
    for attempt in range(5):
        time.sleep(3)
        r = requests.post(pub_url, data={"creation_id": container_id, "access_token": access_token}, timeout=30)
        pub_res = r.json()
        if "id" in pub_res:
            return pub_res["id"]

        err = pub_res.get("error", {})
        err_sub = err.get("error_subcode")
        err_msg = str(err.get("message", ""))
        if err_sub == 4279009 or "does not exist" in err_msg.lower():
            print(f"[RETRY PUBLISH {attempt + 1}/5] Server Meta sedang merakit container {container_id}, jeda 6 detik...")
            time.sleep(6)
        else:
            break

    raise Exception(f"Gagal publish container {container_id}: {pub_res}")

def run_worker():
    print(f"[{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')} WIB] Memeriksa jadwal posting antrean...")
    client = get_sheets_client()
    sh = client.open_by_key(SPREADSHEET_ID)

    acc_ws = sh.worksheet("Accounts")
    acc_records = acc_ws.get_all_records()
    accounts_map = {}
    for a in acc_records:
        name = str(a.get("name", "")).strip()
        uid = str(a.get("user_id", "")).strip()
        token = str(a.get("access_token", "")).strip()
        cat = str(a.get("category", "")).strip()
        if name and uid and token:
            accounts_map[name] = {"user_id": uid, "access_token": token, "category": cat}

    # 1. Update Metrik Harian dari Threads API
    try:
        update_threads_insights(sh, accounts_map)
    except Exception as e:
        print(f"[INSIGHTS ERROR] Terjadi kendala saat update metrik: {e}")

    # 2. Buat Draf Otomatis Berbasis Hasil Self-Learning
    try:
        auto_generate_today_drafts_if_needed(sh, accounts_map)
    except Exception as e:
        print(f"[AUTO-GEN ERROR] Terjadi kendala saat generate otomatis: {e}")

    # 3. Terbitkan Konten yang Jadwalnya Sudah Tiba
    data_ws = sh.worksheet("data")
    rows = data_ws.get_all_values()
    if len(rows) <= 1:
        print("Tabel data kosong.")
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
        aff_link = r[6].strip()
        status = r[7].strip().upper()
        target_hijack_id = r[11].strip()

        if status != "PENDING" or not main_text:
            continue

        try:
            m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", post_date)
            t_m = re.match(r"^(\d{1,2}):(\d{1,2})$", post_time)
            if not m or not t_m:
                continue
            p_dt = TZ.localize(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(t_m.group(1)), int(t_m.group(2))))
        except Exception:
            continue

        if p_dt > now_dt:
            continue

        acc_info = accounts_map.get(target_acc)
        if not acc_info:
            err = f"Akun '{target_acc}' tidak ditemukan di Accounts"
            print(f"[ROW {idx}] {err}")
            data_ws.update_cell(idx, 8, "ERROR")
            data_ws.update_cell(idx, 10, err)
            continue

        u_id = acc_info["user_id"]
        tok = acc_info["access_token"]

        print(f"[ROW {idx}] Memproses postingan untuk @{target_acc}...")
        try:
            main_id = publish_threads_post(u_id, tok, text=main_text, media_raw=media_url, reply_to_id=target_hijack_id)
            print(f"[ROW {idx}] Utama sukses: {main_id}")

            current_parent = main_id
            if reply_chain_text:
                replies = [rep.strip() for rep in reply_chain_text.split("---REPLY---") if rep.strip()]
                for rep_item in replies:
                    time.sleep(3)
                    safe_reply = sanitize_threads_text(rep_item)
                    rep_id = publish_threads_post(u_id, tok, text=safe_reply, media_raw="", reply_to_id=current_parent)
                    current_parent = rep_id
                    print(f"[ROW {idx}] Balasan terbit: {rep_id}")

            data_ws.update_cell(idx, 8, "POSTED")
            data_ws.update_cell(idx, 9, main_id)
            data_ws.update_cell(idx, 10, "")
            data_ws.update_cell(idx, 11, datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"))

        except Exception as ex:
            err_msg = str(ex)[:200]
            print(f"[ROW {idx}] GAGAL: {err_msg}")
            data_ws.update_cell(idx, 8, "ERROR")
            data_ws.update_cell(idx, 10, err_msg)

if __name__ == "__main__":
    run_worker()
