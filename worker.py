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
