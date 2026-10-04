# PostgreSQL profile

The `core` Compose profile uses PostgreSQL 18 with pgvector 0.8.2 and binds only
to `127.0.0.1:55433`. Port 55432 was already occupied during the initial
inventory, so the project uses the next verified-free loopback port. It
requires `KY_JARVIS_DB_PASSWORD_FILE` to reference a
confirmed local secret file outside the repository. The repository does not
generate or persist that secret automatically.
