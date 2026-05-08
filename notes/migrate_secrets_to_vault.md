# migrate_secrets_to_vault.py
## Purpose
One-shot migration script — moves .env secrets into Fernet-encrypted vault.
## Key Functions
- `main()` — load .env, prompt master password, write all keys to vault
- `_get_master_password()` — prompt twice, validate match
- `_load_vault(password)` / `_save_vault(password, vault_data)` — vault read/write
- `_get_key(password, salt)` — Argon2 KDF → Fernet key
## Imports From
none (standalone — uses cryptography + argon2 directly)
## Imported By
none (run once manually)
## Status
OK
## Notes
Run once during initial setup. Does not delete .env after migration — manual cleanup required.
