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

VIRAL_HOOK_PATTERNS = [
    "Trigger Drama Relasi (Pasangan/Mertua): Awali baris pertama dengan dialog/reaksi pasangan atau mertua huruf kapital (misal: 'SUAMI: KAMU KALAU NYUCI KOK RIBET BANGET? 😭😂').",
    "Trigger Nyaris Malu (Social Anxiety): Awali baris pertama dengan momen horor/panik di tempat umum huruf kapital (misal: 'HAMPIR MALU DI RUANG MEETING KANTOR GARA-GARA BASKET 😭💀').",
    "Trigger Otoritas/Orang Dalam: Awali baris pertama dengan ucapan terima kasih huruf kapital ke dokter/ahli yang kasih bocoran (misal: 'MAKASIH MBAK DOKTER YANG UDAH KASI TAU INI 😭🙏').",
    "Trigger Kaum Mager/Satset: Awali baris pertama dengan pengakuan malas huruf kapital tapi nemu jalan pintas (misal: 'SEBAGAI ORANG YANG PALING MALES NYIKAT KAMAR MANDI... 🤣').",
    "Trigger Satisfying/Sensorik: Awali baris pertama dengan kepuasan visual/suara huruf kapital (misal: 'THERAPY TERBAIK MINGGU INI: LIAT AIR RENDAMAN JADI BUTEK COKLAT 🤤😭').",
    "Trigger Parno/Micro-Anxiety: Awali baris pertama dengan rasa cemas/jijik huruf kapital (misal: 'PARNO TIAP LIAT KECOA MUNCUL DARI BAWAH KITCHEN SET 😭').",
    "Trigger Terlambat Sadar (Umur): Awali baris pertama dengan keheranan kenapa baru tahu barang ini sekarang (misal: 'UMUR 27 TAHUN BARU SADAR BENDA KECIL INI NYELAMATIN PUNGGUNG 😭').",
    "Trigger Skeptis Berujung Tobat: Awali baris pertama dengan mengira awalnya cuma gimik iklan huruf kapital (misal: 'KIRAIN CUMA GIMIK IKLAN LEBAY, TERNYATA EMANG SESAKTI ITU 😭')."
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
        print("[GEMINI ERROR] AI_API_KEY kosong atau belum terbaca dari Secrets/Environment!")
        return "Rekomendasi barang praktis yang ngebantu banget aktivitas harian."

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
            res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30).json()
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
            res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30).json()
            if "candidates" in res and res["candidates"]:
                text_out = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_out:
                    return text_out
        except Exception:
            pass

    print("[GEMINI FAILED] Seluruh percobaan model gagal. Menggunakan fallback.")
    return "Rekomendasi barang praktis yang ngebantu banget aktivitas harian."

def generate_slots(total_count, start_time_str="08:15", end_time_str="21:30"):
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

    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] 📅 Belum ada draf untuk hari ini ({today_str}). Menjalankan Auto-Generate...")

    cfg_ws = sh.worksheet("Config")
    cfg_rows = cfg_ws.get_all_values()
    cfg_data = {r[0].strip(): r[1].strip() for r in cfg_rows if len(r) >= 2 and r[0].strip()}

    try:
        start_str = cfg_data.get("start_datetime", "2026-01-01 00:00").replace("'", "")
        end_str = cfg_data.get("end_datetime", "2026-12-31 23:59").replace("'", "")
        start_date = datetime.strptime(start_str.split()[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str.split()[0], "%Y-%m-%d").date()
        if not (start_date <= now_dt.date() <= end_date):
            print(f"[AUTO-GEN] Tanggal hari ini di luar rentang jadwal aktif ({start_date} s/d {end_date}). Lewati.")
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

    prods_with_media = [p for p in ready_prods if str(p.get("media_url", "")).strip()]
    prods_text_only = [p for p in ready_prods if not str(p.get("media_url", "")).strip()] or ready_prods

    total_plan = daily_viral + daily_text + daily_video
    slots = generate_slots(total_plan)
    types_list = arrange_post_types_3way(daily_viral, daily_text, daily_video)

    new_rows = []
    for acc_name in target_accounts:
        sampled_video = random.sample(prods_with_media, min(daily_video, len(prods_with_media))) if (daily_video > 0 and prods_with_media) else []
        sampled_text = random.sample(prods_text_only, min(daily_text, len(prods_text_only))) if (daily_text > 0 and prods_text_only) else []

        v_i, t_i = 0, 0
        for slot_time, p_type in zip(slots, types_list):
            if p_type == "viral":
                cat = random.choice(list(TOPIC_PILLARS.keys()))
                sub_top = random.choice(TOPIC_PILLARS[cat])
                prompt_v = (
                    f"Tulis 1 postingan Threads bahasa Indonesia tentang: '{sub_top}'.\n"
                    f"{PROMPT_RULES_CLEAN}\n"
                    f"Maksimal 220 karakter tanpa tanda kutip."
                )
                p_text = call_gemini(prompt_v)
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(p_text), "", "", "", "PENDING", "", "", "", ""])

            elif p_type == "video":
                p_cur = sampled_video[v_i] if v_i < len(sampled_video) else random.choice(ready_prods)
                v_i += 1
                hook = random.choice(VIRAL_HOOK_PATTERNS)
                prompt = (
                    f"Tulis 1 postingan Threads bahasa Indonesia penahan jempol (stop scrolling) penonton video untuk produk: '{p_cur['product_name']}' "
                    f"(Keunggulan: {p_cur.get('highlight', '')}).\n"
                    f"- Formula Hook: {hook}\n"
                    f"{PROMPT_RULES_CLEAN}\n"
                    f"Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji penahan jempol dalam 1-3 detik. Maksimal 300 karakter tanpa tanda kutip."
                )
                main_txt = call_gemini(prompt)
                closing = random.choice(CLOSING_NARRATIVES)
                aff_reply = f"{closing}\n{p_cur['affiliate_link']}"
                media_formatted = prepare_media_for_post(str(p_cur.get("media_url", "")).strip(), duplicate_single_video=True)
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(main_txt), media_formatted, sanitize_threads_text(aff_reply), p_cur['affiliate_link'], "PENDING", "", "", "", ""])

            else:
                p_cur = sampled_text[t_i] if t_i < len(sampled_text) else random.choice(ready_prods)
                t_i += 1
                hook = random.choice(VIRAL_HOOK_PATTERNS)
                prompt = (
                    f"Tulis 1 postingan Threads bahasa Indonesia rekomendasi produk: '{p_cur['product_name']}' "
                    f"(Keunggulan: {p_cur.get('highlight', '')}).\n"
                    f"- Formula Hook: {hook}\n"
                    f"{PROMPT_RULES_CLEAN}\n"
                    f"Baris 1 WAJIB 1 kalimat pendek HURUF KAPITAL + 1-2 emoji penahan jempol dalam 1-3 detik. Maksimal 300 karakter tanpa tanda kutip."
                )
                main_txt = call_gemini(prompt)
                closing = random.choice(CLOSING_NARRATIVES)
                aff_reply = f"{closing}\n{p_cur['affiliate_link']}"
                new_rows.append([today_str, slot_time, acc_name, sanitize_threads_text(main_txt), "", sanitize_threads_text(aff_reply), p_cur['affiliate_link'], "PENDING", "", "", "", ""])

    for row_item in new_rows:
        data_ws.append_row(row_item)

    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] ✅ Berhasil membuat {len(new_rows)} draf otomatis untuk hari ini!")

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
        if name and uid and token:
            accounts_map[name] = {"user_id": uid, "access_token": token}

    try:
        auto_generate_today_drafts_if_needed(sh, accounts_map)
    except Exception as e:
        print(f"[AUTO-GEN ERROR] Terjadi kendala saat generate otomatis: {e}")

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
