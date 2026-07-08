"""
supabase_db.py
================
Modul shared database untuk status akun & langganan.

KENAPA INI PERLU (ganti dari user_db.json):
Sebelumnya status langganan disimpan di file JSON lokal (user_db.json).
Itu HANYA bisa dibaca-tulis oleh proses yang sama di mesin yang sama.
Begitu ada 2 layanan terpisah (app Streamlit + backend webhook pembayaran
yang di-deploy di server lain), file lokal itu TIDAK akan sinkron —
webhook akan menulis ke disknya sendiri, sementara Streamlit membaca
dari disknya sendiri. Makanya perlu database yang benar-benar "shared"
lewat jaringan: di sini pakai Supabase (Postgres via REST API).

SETUP SUPABASE (sekali saja):
1. Buat project gratis di https://supabase.com
2. Buka SQL Editor, jalankan:

    create table if not exists users (
        username text primary key,
        password_hash text not null,
        salt text not null,
        status text not null default 'inactive',
        last_order_id text,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now()
    );

3. Ambil "Project URL" dan "service_role key" dari Project Settings > API.
   - service_role key ini PUNYA HAK PENUH (bypass RLS) — taruh HANYA di
     server backend (Streamlit secrets & Flask webhook env var), JANGAN
     PERNAH taruh di kode frontend/browser/publik.
4. Set sebagai environment variable / st.secrets:
   SUPABASE_URL, SUPABASE_KEY (isi dengan service_role key)

Install dependency:
    pip install supabase
"""

import os
from datetime import datetime, timezone

try:
    from supabase import create_client
except ImportError:  # biar file ini tidak bikin crash kalau belum di-pip-install
    create_client = None

_client = None


def _get_env(name):
    # Coba ambil dari st.secrets dulu (kalau dipanggil dari dalam Streamlit),
    # baru fallback ke environment variable biasa (kalau dipanggil dari Flask).
    try:
        import streamlit as st
        val = st.secrets.get(name)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(name)


def get_client():
    global _client
    if _client is None:
        if create_client is None:
            raise RuntimeError(
                "Package 'supabase' belum terinstall. Jalankan: pip install supabase"
            )
        url = _get_env("SUPABASE_URL")
        key = _get_env("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_KEY belum diset di secrets/environment."
            )
        _client = create_client(url, key)
    return _client


def get_user(username):
    """Ambil satu record user berdasarkan username. None kalau belum ada."""
    res = get_client().table("users").select("*").eq("username", username).limit(1).execute()
    return res.data[0] if res.data else None


def create_user(username, password_hash, salt):
    """Daftar user baru, status default 'inactive'."""
    get_client().table("users").insert({
        "username": username,
        "password_hash": password_hash,
        "salt": salt,
        "status": "inactive",
    }).execute()


def set_status(username, status, order_id=None):
    """Update status langganan user (dipanggil oleh webhook pembayaran,
    dan bisa juga dipanggil manual oleh admin/owner)."""
    payload = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if order_id:
        payload["last_order_id"] = order_id
    get_client().table("users").update(payload).eq("username", username).execute()


def set_pending_order(username, order_id):
    """Catat order_id yang baru dibuat, supaya gampang ditelusuri kalau perlu
    cek manual status pembayaran mana yang terhubung ke user mana."""
    get_client().table("users").update({
        "last_order_id": order_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("username", username).execute()
