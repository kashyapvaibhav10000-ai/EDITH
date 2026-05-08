"""
EDITH Secret Migration — One-shot script to move .env secrets into the encrypted vault.

Usage:
    python migrate_secrets_to_vault.py

What it does:
    1. Reads all secrets from .env
    2. Stores each one in the encrypted vault (vault.enc)
    3. Rewrites .env with ONLY non-sensitive config values
    4. Verifies all secrets are readable from vault

Requires: ~/.edith/vault_key to exist (or EDITH_MASTER_KEY env var)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Direct vault operations to avoid config.py circular import
import json
import base64
import os
import sys
from cryptography.fernet import Fernet
from argon2.low_level import hash_secret_raw, Type
from dotenv import dotenv_values

EDITH_PATH = os.path.dirname(os.path.abspath(__file__))
VAULT_PATH = os.path.join(EDITH_PATH, "vault.enc")
VAULT_SALT_PATH = os.path.join(EDITH_PATH, "vault.salt")
VAULT_KEY_PATH = os.path.expanduser("~/.edith/vault_key")

def _get_key(password, salt):
    key = hash_secret_raw(password.encode(), salt, time_cost=3, memory_cost=65536,
                          parallelism=2, hash_len=32, type=Type.ID)
    return base64.urlsafe_b64encode(key)

def _get_master_password():
    if "EDITH_MASTER_KEY" in os.environ:
        return os.environ["EDITH_MASTER_KEY"]
    if os.path.exists(VAULT_KEY_PATH):
        with open(VAULT_KEY_PATH, "r") as f:
            return f.read().strip()
    return None

def _load_vault(password):
    if not os.path.exists(VAULT_PATH):
        return {}
    salt = open(VAULT_SALT_PATH, "rb").read()
    key = _get_key(password, salt)
    f = Fernet(key)
    try:
        data = f.decrypt(open(VAULT_PATH, "rb").read())
        return json.loads(data)
    except Exception:
        return None

def _save_vault(password, vault_data):
    if not os.path.exists(VAULT_SALT_PATH):
        salt = os.urandom(16)
        with open(VAULT_SALT_PATH, "wb") as sf:
            sf.write(salt)
    salt = open(VAULT_SALT_PATH, "rb").read()
    key = _get_key(password, salt)
    f = Fernet(key)
    encrypted = f.encrypt(json.dumps(vault_data).encode())
    tmp_path = f"{VAULT_PATH}.tmp"
    with open(tmp_path, "wb") as vf:
        vf.write(encrypted)
    os.replace(tmp_path, VAULT_PATH)

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# These keys contain secrets and MUST be moved to the vault
SECRET_KEYS = [
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_TOKEN",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "NVIDIA_API_KEY",
    "OPENROUTER_API_KEY",
    "SIMPLENOTE_EMAIL",
    "SIMPLENOTE_PASSWORD",
]

# These keys are non-sensitive config and stay in .env
SAFE_KEYS = [
    "WHATSAPP_BRIDGE_URL",
    "EDITH_CITY",
    "EDITH_LAT",
    "EDITH_LON",
]


def main():
    print("=" * 55)
    print("  EDITH Secret Migration: .env → Encrypted Vault")
    print("=" * 55)

    # 1. Check vault access
    master = _get_master_password()
    if not master:
        print("\n❌ Cannot access vault. Ensure one of these exists:")
        print("   • ~/.edith/vault_key (chmod 400)")
        print("   • EDITH_MASTER_KEY environment variable")
        sys.exit(1)
    print("✅ Vault access confirmed.")

    # 2. Load current .env
    env_values = dotenv_values(ENV_PATH)
    if not env_values:
        print("❌ No values found in .env")
        sys.exit(1)
    print(f"✅ Loaded {len(env_values)} values from .env")

    # 3. Load existing vault
    vault = _load_vault(master)
    if vault is None:
        print("❌ Failed to decrypt vault. Wrong password?")
        sys.exit(1)
    print(f"✅ Vault loaded ({len(vault)} existing entries)")

    # 4. Migrate secrets to vault
    migrated = 0
    for key in SECRET_KEYS:
        value = env_values.get(key)
        if value:
            if key in vault:
                print(f"   ⚠️  {key}: already in vault, overwriting with .env value")
            else:
                print(f"   ✅ {key}: migrating to vault")
            vault[key] = value
            migrated += 1
        else:
            print(f"   ⏭️  {key}: not found in .env, skipping")

    # 5. Save vault
    _save_vault(master, vault)
    print(f"\n✅ Vault saved with {migrated} new/updated secrets")

    # 6. Rewrite .env with only safe values
    safe_lines = [
        "# EDITH Configuration — Non-sensitive values only",
        "# All secrets are stored in the encrypted vault (vault.enc)",
        "# Run: python migrate_secrets_to_vault.py to manage secrets",
        "",
    ]
    for key in SAFE_KEYS:
        value = env_values.get(key, "")
        if value:
            safe_lines.append(f'{key}="{value}"')

    with open(ENV_PATH, "w") as f:
        f.write("\n".join(safe_lines) + "\n")
    print(f"✅ .env rewritten with {len(SAFE_KEYS)} safe config values only")

    # 7. Verify all secrets readable from vault
    print("\n--- Verification ---")
    vault_check = _load_vault(master)
    all_ok = True
    for key in SECRET_KEYS:
        value = env_values.get(key)
        if value:
            stored = vault_check.get(key)
            if stored == value:
                print(f"   ✅ {key}: verified in vault")
            else:
                print(f"   ❌ {key}: MISMATCH!")
                all_ok = False

    if all_ok:
        print("\n" + "=" * 55)
        print("  ✅ Migration complete! All secrets are in the vault.")
        print("  .env now contains only non-sensitive config.")
        print("=" * 55)
    else:
        print("\n❌ Some secrets failed verification. Check vault.enc")
        sys.exit(1)


if __name__ == "__main__":
    main()
