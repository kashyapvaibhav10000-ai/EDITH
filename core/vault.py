import json
import os
import stat
import shutil
import getpass
import base64
from cryptography.fernet import Fernet

try:
    from argon2.low_level import hash_secret_raw, Type
    _ARGON2_AVAILABLE = True
except ImportError:
    _ARGON2_AVAILABLE = False
    # Fallback to SHA256 if argon2 not available
    import hashlib
    def hash_secret_raw(password, salt, time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, type=None):
        return hashlib.pbkdf2_hmac('sha256', password, salt, 100000, dklen=hash_len)
    Type = None

from config import VAULT_PATH, VAULT_SALT_PATH, get_logger

log = get_logger("vault")

def _check_keyfile_perms(path):
    mode = oct(stat.S_IMODE(os.stat(path).st_mode))
    if not mode.endswith('400'):
        raise PermissionError(f"Keyfile {path} perms too open: {mode}. Run: chmod 400 {path}")

def get_key(password, salt):
    if _ARGON2_AVAILABLE:
        key = hash_secret_raw(password.encode(), salt, time_cost=3, memory_cost=65536,
                              parallelism=2, hash_len=32, type=Type.ID)
    else:
        # Fallback: use PBKDF2 if argon2 not available
        key = hash_secret_raw(password.encode(), salt)
    return base64.urlsafe_b64encode(key)

def get_master_password():
    if "EDITH_MASTER_KEY" in os.environ:
        return os.environ["EDITH_MASTER_KEY"]
    key_path = os.path.expanduser("~/.edith/vault_key")
    if os.path.exists(key_path):
        _check_keyfile_perms(key_path)
        with open(key_path, "r") as f:
            return f.read().strip()
    return None

def load_vault(password=None):
    if password is None:
        password = get_master_password()
    if not password:
        return None
    if not os.path.exists(VAULT_PATH):
        return {}
        
    with open(VAULT_SALT_PATH, "rb") as _sf:
        salt = _sf.read()
    key = get_key(password, salt)
    fernet = Fernet(key)
    try:
        with open(VAULT_PATH, "rb") as _vf:
            data = fernet.decrypt(_vf.read())
        return json.loads(data)
    except Exception:
        print("[EDITH Vault] Wrong password or corrupted vault.")
        return None

def save_vault(password, vault):
    if not os.path.exists(VAULT_SALT_PATH):
        salt = os.urandom(16)
        with open(VAULT_SALT_PATH, "wb") as sf:
            sf.write(salt)
            
    with open(VAULT_SALT_PATH, "rb") as _sf:
        salt = _sf.read()
    key = get_key(password, salt)
    f = Fernet(key)
    encrypted = f.encrypt(json.dumps(vault).encode())
    
    if os.path.exists(VAULT_PATH):
        shutil.copy2(VAULT_PATH, f"{VAULT_PATH}.bak")
        
    # Write atomically
    tmp_path = f"{VAULT_PATH}.tmp"
    with open(tmp_path, "wb") as vf:
        vf.write(encrypted)
    os.replace(tmp_path, VAULT_PATH)
    # Enforce owner-only permissions — vault must not be world-readable
    os.chmod(VAULT_PATH, 0o600)
    os.chmod(VAULT_SALT_PATH, 0o600)

def rotate_key(old_password, new_password):
    vault = load_vault(old_password)
    if vault is None:
        print("Cannot decrypt vault with the current password.")
        return False
    save_vault(new_password, vault)
    print("Vault key rotated successfully.")
    return True

def get_secret(key, default=None):
    vault = load_vault()
    if vault is not None and key in vault:
        entry = vault.get(key)
        if isinstance(entry, dict) and 'password' in entry:
            return entry['password']
        return entry
    return default


def set_secret(key: str, value: str, password: str = None) -> bool:
    """Store or update a secret in the vault. Returns True on success."""
    try:
        pwd = password or get_master_password()
        if not pwd:
            return False
        current = load_vault(pwd) or {}
        current[key] = value
        save_vault(pwd, current)
        return True
    except Exception:
        return False

def vault_menu():
    print("\n[EDITH Vault] Local Encrypted Password Manager")
    master = get_master_password()
    if master is None:
        print("Warning: '~/.edith/vault_key' not found. Using manual interactive unlock.")
        master = getpass.getpass("Master password: ")
        
    if not os.path.exists(VAULT_PATH):
        print("[EDITH Vault] Creating new vault...")
        confirm = getpass.getpass("Confirm master password: ")
        if master != confirm:
            print("Passwords do not match!")
            return
        save_vault(master, {})
        print("[EDITH Vault] Vault created!")
        
    vault = load_vault(master)
    if vault is None:
        return
        
    while True:
        print("\n1. Get password")
        print("2. Add password")
        print("3. List all entries")
        print("4. Delete entry")
        print("5. Rotate master key")
        print("6. Exit")
        choice = input(">> ").strip()
        if choice == "1":
            name = input("Search: ").strip().lower()
            matches = {k: v for k, v in vault.items() if name in k.lower()}
            if not matches:
                print("No matches found.")
            for k, v in matches.items():
                print(f"\n  Name     : {k}")
                if isinstance(v, dict):
                    print(f"  Username : {v.get('username', 'N/A')}")
                    print(f"  Password : {v.get('password', 'N/A')}")
                    print(f"  Notes    : {v.get('notes', '')}")
                else:
                    print(f"  Secret   : {v}")
        elif choice == "2":
            name = input("Name/Key (e.g. GEMINI_API_KEY): ").strip()
            username = input("Username/Email (optional): ").strip()
            password = getpass.getpass("Password/Secret: ")
            notes = input("Notes (optional): ").strip()
            vault[name] = {"username": username, "password": password, "notes": notes}
            save_vault(master, vault)
            print(f"[EDITH Vault] Saved: {name}")
            log.info(f"Vault entry added: {name}")
        elif choice == "3":
            if not vault:
                print("Vault is empty.")
            else:
                print(f"\n[EDITH Vault] {len(vault)} entries:")
                for k in vault:
                    if isinstance(vault[k], dict):
                        print(f"  - {k} ({vault[k].get('username', '')})")
                    else:
                        print(f"  - {k}")
        elif choice == "4":
            name = input("Delete which entry: ").strip()
            if name in vault:
                confirm = input(f"Delete '{name}'? [y/n]: ").strip().lower()
                if confirm == "y":
                    del vault[name]
                    save_vault(master, vault)
                    print(f"Deleted: {name}")
                    log.info(f"Vault entry deleted: {name}")
            else:
                print("Not found.")
        elif choice == "5":
            new_pass = getpass.getpass("New master password: ")
            confirm = getpass.getpass("Confirm new password: ")
            if new_pass != confirm:
                print("Passwords do not match!")
            else:
                if rotate_key(master, new_pass):
                    master = new_pass
        elif choice == "6":
            print("[EDITH Vault] Locked.")
            break

if __name__ == "__main__":
    vault_menu()
