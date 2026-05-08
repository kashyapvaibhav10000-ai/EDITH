# vault.py
## Purpose
Fernet-encrypted password/secret store with Argon2 KDF and file permission hardening.
## Key Functions
- `get_secret(key, default)` — load vault, return decrypted secret
- `set_secret(key, value, password)` — add/update secret in vault
- `load_vault(password)` / `save_vault(password, vault)` — full vault read/write
- `rotate_key(old_password, new_password)` — re-encrypt all secrets with new key
- `vault_menu()` — interactive CLI for vault management
- `get_master_password()` — prompt with confirmation
- `get_key(password, salt)` — Argon2id KDF → Fernet key
- `_check_keyfile_perms(path)` — warn if vault file world-readable
## Imports From
config
## Imported By
devlog, email_reader, search, smart_router, telegram_bot, vision
## Status
OK
## Notes
vault.enc + vault.salt never committed. Argon2id params: time=2, memory=65536, parallelism=2.
