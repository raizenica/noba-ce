# NOBA Enterprise Setup Guide

Enterprise features (SAML SSO, SCIM provisioning, WebAuthn passkeys, PostgreSQL and MySQL backends)
are configured from **Settings → enterprise tabs** in the NOBA UI. No SSH or env-file editing is
required for runtime configuration.

---

## Prerequisites

- NOBA 2.x running with admin account
- For PostgreSQL: `psycopg2-binary` installed (`pip install psycopg2-binary`)
- For MySQL: `PyMySQL` installed (`pip install PyMySQL`)
- For SAML: IdP metadata (SSO URL + X.509 certificate)
- For SCIM: Okta, Azure AD, or compatible IdP with SCIM 2.0 support

---

## SAML SSO

1. In your IdP (Okta, Azure AD, etc.), create a new SAML application.
2. In NOBA **Settings → SAML SSO**:
   - Paste the **IdP SSO URL** and **IdP Certificate (PEM)** from your IdP's metadata.
   - Copy the **SP Metadata URL** (`<noba-origin>/api/saml/metadata`) into your IdP's configuration.
   - Set **SP Entity ID** and **ACS URL** (auto-filled; must match your IdP application settings).
   - Set **Default role** for newly provisioned SAML users (`viewer` recommended).
   - Optionally set **Role mapping JSON** to map IdP groups to NOBA roles:
     ```json
     {"Admins": "admin", "Operators": "operator"}
     ```
3. Click **Test Connection** to verify IdP reachability.
4. Enable **Enable SAML SSO** and click **Save**.

Users visiting the NOBA login page will see a "Sign in with SSO" option.

---

## SCIM Provisioning

1. In NOBA **Settings → SCIM**:
   - Click **Generate Token**.
   - Copy the token immediately — it is shown only once.
   - Copy the **SCIM Base URL** (`<noba-origin>/api/scim/v2`).
2. In your IdP, configure SCIM 2.0 provisioning:
   - Paste the SCIM Base URL as the tenant URL.
   - Paste the token as the API secret / bearer token.
   - Map user attributes: `userName → username`, `emails → email`.
3. Test the connection in your IdP and enable provisioning.

NOBA supports the **Users** resource (create, update, deactivate). Groups are not currently supported.

To rotate the token, click **Rotate Token** in the SCIM tab and update your IdP.

---

## PostgreSQL Backend

NOBA uses SQLite by default. Switch to PostgreSQL for multi-instance deployments or higher write throughput.

### Fresh install

1. Create a PostgreSQL database:
   ```sql
   CREATE DATABASE noba;
   CREATE USER noba WITH PASSWORD 'yourpassword';
   GRANT ALL PRIVILEGES ON DATABASE noba TO noba;
   ```

2. Install the driver:
   ```bash
   pip install psycopg2-binary
   ```

3. Set `DATABASE_URL` and start NOBA — schema is auto-created on first run:
   ```bash
   export DATABASE_URL=postgresql://noba:yourpassword@localhost:5432/noba
   noba-web
   ```

### Migrating from SQLite (existing install)

The migration script **automatically stops the running NOBA server** before migrating to ensure a consistent snapshot, then prints the command to restart on the new backend.

```bash
DATABASE_URL=postgresql://noba:yourpassword@localhost:5432/noba \
  python3 scripts/migrate-to-postgres.py
```

Pass `--keep-running` to skip the auto-stop (e.g. when NOBA is not currently running):
```bash
DATABASE_URL=postgresql://... python3 scripts/migrate-to-postgres.py --keep-running
```

After migration completes, restart NOBA with `DATABASE_URL` set — it will connect to PostgreSQL on startup.

### Schema management with noba-migrate

For environments where DBAs manage schema separately from application deployments:

```bash
# Check current schema version
noba-migrate status

# Apply all pending migrations
noba-migrate upgrade

# View full migration history
noba-migrate history

# Mark existing schema as current (for databases bootstrapped by the server)
noba-migrate stamp 001
```

### Configuration

The **Settings → Database** tab shows the active backend, connection status, and pool configuration.

Pool size is tunable via env vars (defaults: min=1, max=10):
```bash
NOBA_PG_POOL_MIN=2
NOBA_PG_POOL_MAX=20
```

---

## MySQL Backend

MySQL is a **migration target only** — NOBA does not use MySQL as a runtime backend. Use this to export NOBA data into an existing MySQL/MariaDB database for reporting, analytics, or integration with other systems.

### Setup

1. Create the database:
   ```sql
   CREATE DATABASE noba CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'noba'@'localhost' IDENTIFIED BY 'yourpassword';
   GRANT ALL PRIVILEGES ON noba.* TO 'noba'@'localhost';
   FLUSH PRIVILEGES;
   ```

2. Install the driver:
   ```bash
   pip install PyMySQL
   ```

3. Initialise the schema (introspected directly from the SQLite source — always matches):
   ```bash
   DATABASE_URL=mysql://noba:yourpassword@localhost:3306/noba \
     python3 scripts/init-mysql-schema.py
   ```

4. Migrate data (auto-stops NOBA server for a consistent snapshot):
   ```bash
   DATABASE_URL=mysql://noba:yourpassword@localhost:3306/noba \
     python3 scripts/migrate-to-mysql.py
   ```

Pass `--keep-running` to skip the auto-stop if NOBA is not running:
```bash
DATABASE_URL=mysql://... python3 scripts/migrate-to-mysql.py --keep-running
```

The migration uses `INSERT IGNORE` — safe to re-run; duplicate rows are silently skipped.

---

## WebAuthn Passkeys

Users register their own passkeys from the NOBA **login screen** using any FIDO2-compatible authenticator
(hardware security key, Touch ID, Windows Hello, etc.).

As an admin, the **Settings → WebAuthn** tab lists all registered passkeys across all users. You can
revoke any passkey from this view (e.g., for a lost device or departed employee).
