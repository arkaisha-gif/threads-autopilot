import os
import re
import json
import base64
import time
from datetime import datetime
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

def sanitize_threads_text(text: str, max_chars: int = 495) -> str:
    if not text:
        return ""
    text_str = str(text).strip()
    if len(text_str) > max_chars:
        return text_str[:max_chars - 3].rstrip() + "..."
    return text_str

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

def wait_for_container(container_id: str, access_token: str, max_wait: int = 120) -> bool:
    url = f"https://graph.threads.net/v1.0/{container_id}?fields=status,error_message&access_token={access_token}"
    start = time.time()
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
        time.sleep(5)
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
            if any(m_url.lower().endswith(ext) for ext in [".mp4", ".mov", ".m4v"]) or "/video/upload/" in m_url:
                if not wait_for_container(c_id, access_token):
                    raise Exception(f"Video carousel item {c_id} gagal diproses Threads")
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

    elif len(media_list) == 1:
        m_url = media_list[0]
        container_id = create_single_media_container(user_id, access_token, m_url, text=text, reply_to_id=reply_to_id)
        if any(m_url.lower().endswith(ext) for ext in [".mp4", ".mov", ".m4v"]) or "/video/upload/" in m_url:
            if not wait_for_container(container_id, access_token):
                raise Exception(f"Video {container_id} gagal diproses Threads")
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

    pub_url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
    pub_res = requests.post(pub_url, data={"creation_id": container_id, "access_token": access_token}, timeout=30).json()
    if "id" not in pub_res:
        raise Exception(f"Gagal publish container {container_id}: {pub_res}")
    return pub_res["id"]

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
