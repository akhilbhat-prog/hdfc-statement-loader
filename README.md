# ExpTrack

A personal financial pipeline that polls HDFC Bank transaction alert emails via Gmail, parses and stores them in a PostgreSQL database, categorises them with a rules → memory → ML pipeline, and surfaces them through four web UIs for review, editing, shared expense tracking, and recurring transaction management. The four UIs are a React SPA (`frontend/`) served by Flask. Runs on Google Cloud Run, triggered daily by Cloud Scheduler.

---

## What it does

1. **Gmail poller** (`loader/gmail_poller.py`) searches for HDFC alert emails (4 formats: UPI debit/credit, NetBanking, Debit Card) and stores parsed transactions in the `transactions` table.
2. **Categoriser** (`categorizer/batch_process.py`) runs a rules → merchant-memory → LightGBM ML pipeline, creating batches of predictions in `transaction_batch_items`.
3. **Batch review UI** (`/review`) lets you edit and approve categorised batches. On completion, rows move to `data_feed_history` and the ML model retrains.
4. **History editor** (`/view`) provides full CRUD over `data_feed_history` with period filtering, inline editing, and period-vs-period spend summaries.
5. **Shared expenses ledger** (`/shared`) mirrors shared-expense rows into `shared_transactions` and tracks balances, settlements, and payments between Akhil and Aditi.
6. **Recurring transactions manager** (`/recurring`) defines recurring expenses that are auto-generated monthly into `data_feed_history`.
7. **Nightly summary email** is sent after each run with transaction counts, failures, and categorisation status.

---

## Web UI pages

| Page | Route | Purpose |
|------|-------|---------|
| Batch Review | `/review` | Edit and approve ML-predicted categories; complete batches to finalize |
| History Editor | `/view` | Browse and edit `data_feed_history` by period; add manual entries |
| Shared Expenses | `/shared` | Track shared expenses with balances, settlements, and payments by FY |
| Recurring Manager | `/recurring` | Define auto-generated monthly/annual recurring entries |

---

## API routes

### Review (`loader/review.py`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/batches` | List batches (`?include_complete=1` for all) |
| GET | `/api/batches/<id>` | Batch detail + items |
| PATCH | `/api/batches/<id>/items/<txn_id>` | Edit category/subcategory/type/cadence/divide_by/shared_expense/share_ratio/amount |
| DELETE | `/api/batches/<id>/items/<txn_id>` | Remove item; adds to `transaction_exclusions` |
| DELETE | `/api/batches/<id>` | Delete pending/reviewed batch |
| POST | `/api/batches/<id>/mark-reviewed` | Transition batch to `reviewed` |
| POST | `/api/batches/<id>/complete` | Finalize to `data_feed_history`, mirror shared rows, trigger retraining |
| GET | `/api/categories` | `{categories, types}` merged from `rules.json` + `data_feed_history` |

### History (`loader/history.py`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/history/periods` | Distinct `time_period` values with row counts, newest first |
| GET | `/api/history` | Paginated rows (`?period=May-2026&page=1`) |
| GET | `/api/history/summary` | Top-5 categories + period total (`?period=&prev_period=` optional) |
| POST | `/api/history` | Create manual entry; cadence=A + divide_by>1 auto-generates future rows |
| PATCH | `/api/history/<id>` | Update row fields; recomputes monthly_amount and final_amount |
| DELETE | `/api/history/<id>` | Delete row |
| GET | `/api/settings` | Return `{default_share_ratio, default_annual_divisor}` |
| PATCH | `/api/settings` | Update allowed settings keys |

### Shared (`loader/shared.py`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/shared/fy-list` | FY start years present in `shared_transactions` |
| GET | `/api/shared` | All rows for FY (`?fy=2026`) |
| GET | `/api/shared/summary` | `{net_balance, total_akhil_paid, total_aditi_paid}` for FY |
| POST | `/api/shared` | Bulk-insert manual shared entries |
| POST | `/api/shared/payment` | Record a settlement payment |
| PATCH | `/api/shared/<id>` | Update paid_by/owed_by/share_ratio/settled/is_ignored |
| DELETE | `/api/shared/<id>` | Delete shared row |

### Recurring (`loader/recurring.py`)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/recurring` | List all recurring definitions |
| POST | `/api/recurring` | Create new definition |
| PUT | `/api/recurring/<id>` | Update definition |
| DELETE | `/api/recurring/<id>` | Delete definition |
| POST | `/api/recurring/generate` | Manually trigger generation (`?date=YYYY-MM-DD` optional) |

### Auth (`loader/auth_routes.py`)
| Method | Route | Description |
|--------|-------|-------------|
| GET/POST | `/login` | Login form; sets session cookie |
| GET | `/logout` | Clear session |
| GET/POST | `/register` | Registration form (requires `INVITE_CODE`) |
| GET | `/api/me` | Current user `{username, role}` for the SPA, or 401 |

Page routes (`/review`, `/view`, `/shared`, `/recurring`) are all served by the React SPA via `loader/app.py`'s `spa_catch_all` — see [Project structure](#project-structure).

---

## Database tables

| Table | Purpose |
|-------|---------|
| `transactions` | Raw parsed bank transactions (one per email alert) |
| `processed_emails` | Idempotency log for every Gmail message ID |
| `transaction_exclusions` | Transactions removed from review batches |
| `transaction_batches` | Batch lifecycle: pending → reviewed → complete |
| `transaction_batch_items` | Per-transaction ML predictions and human edits |
| `data_feed_history` | Ground-truth categorised transactions (the canonical table) |
| `recurring_transactions` | User-defined recurring entries auto-generated monthly |
| `shared_transactions` | Mirror of shared-expense rows with balance tracking |
| `app_settings` | Configurable defaults (`default_share_ratio`, `default_annual_divisor`) |

---

## Environment variables

### Loader

| Variable | Required | Description |
|----------|----------|-------------|
| `GMAIL_CLIENT_ID` | Yes | OAuth2 client ID |
| `GMAIL_CLIENT_SECRET` | Yes | OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | Yes | Long-lived refresh token |
| `DATABASE_URL` | Yes | Neon PostgreSQL connection string |
| `NOTIFICATION_EMAIL` | Yes | Recipient for nightly summary email |
| `POLL_DAYS` | No | Days back to search (default: `1`) |
| `AFTER_DATE` | No | Override `POLL_DAYS` with a `YYYY/MM/DD` date |
| `MAX_MESSAGES` | No | Cap on messages processed (default: no limit) |
| `ADMIN_TOKEN` | No | If set, admin `/api/*` routes require `?token=` or `Authorization: Bearer`. The SPA page shell is always served; auth is enforced on the underlying API calls. |
| `PORT` | No | Flask server port (default: `8080`) |

### Categoriser

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Same Neon connection string |
| `GCS_MODEL_BUCKET` | Yes | GCS bucket for model artefacts |

---

## Running locally

```bash
# Install dependencies
pip install -r requirements.txt -r categorizer/requirements.txt pytest

# Run tests (no DB or network required)
pytest tests/ -v

# Run the full pipeline
python loader/gmail_poller.py

# Serve the web UI locally
cd loader && PORT=5000 python app.py
# then open http://localhost:5000/view
```

For frontend development with hot reload, see [`frontend/README.md`](frontend/README.md) — `npm run dev` proxies API calls to the Flask server above.

---

## Obtaining Gmail OAuth2 credentials

1. In [Google Cloud Console](https://console.cloud.google.com), create an OAuth 2.0 Client ID of type *Desktop app*.
2. Download the JSON as `credentials.json`.
3. Run the one-time authorisation flow:
   ```bash
   python loader/auth.py
   ```
4. Copy the printed `GMAIL_REFRESH_TOKEN` into `.env` and into GCP Secret Manager.

---

## Docker

```bash
docker build -t exptrack .

docker run --rm \
  -e GMAIL_CLIENT_ID="..." \
  -e GMAIL_CLIENT_SECRET="..." \
  -e GMAIL_REFRESH_TOKEN="..." \
  -e DATABASE_URL="postgresql://..." \
  -e NOTIFICATION_EMAIL="you@example.com" \
  exptrack
```

---

## Deployment (Google Cloud Run)

Deployments are fully automated via GitHub Actions on every push to `main` (test → build → push to Artifact Registry → deploy to Cloud Run).

- **GCP project:** `exptrack-privet-drive`
- **Cloud Run service:** `exptrack` (region: `asia-south1`)
- **Artifact Registry:** `asia-south1-docker.pkg.dev/exptrack-privet-drive/exptrack/exptrack:latest`
- **Cloud Scheduler job:** `exptrack-daily` — `0 21 * * *` UTC (9 PM IST)
- **Service URL:** `https://exptrack-878109220582.asia-south1.run.app`

### On-demand trigger

```bash
curl "https://exptrack-878109220582.asia-south1.run.app/trigger?token=YOUR_ADMIN_TOKEN"
```

Response:
```json
{
  "status": "ok",
  "processed": 2,
  "skipped": 0,
  "failed": 0,
  "recurring_generated": 0,
  "message": "2 transaction(s) processed."
}
```

---

## Project structure

```
exptrack/
├── loader/
│   ├── app.py                # Flask entry point; registers blueprints, spa_catch_all
│   ├── gmail_poller.py       # Gmail polling, email parsing, summary email
│   ├── parser.py             # 4-format email parser + inline test suite
│   ├── db.py                 # All DB helpers (9 tables)
│   ├── review.py             # /api/batches, /api/categories (batch review)
│   ├── history.py            # /api/history/* (history editor)
│   ├── shared.py             # /api/shared/* (shared expenses)
│   ├── recurring.py          # /api/recurring/* (recurring transactions)
│   ├── token_auth.py         # require_admin, require_any_auth decorators
│   ├── auth_routes.py        # /login, /logout, /register, /api/me
│   └── auth.py               # One-time OAuth2 setup
├── frontend/                 # React + Vite + TS SPA for /review, /view, /shared, /recurring
│   ├── src/pages/             # Review.tsx, View.tsx, Shared.tsx, Recurring.tsx
│   ├── src/api/               # Fetch wrappers per blueprint
│   └── vite.config.ts         # build.outDir → ../static/dist
├── categorizer/
│   ├── batch_process.py      # Batch classification entry point
│   ├── main.py                # Model retraining pipeline
│   ├── config/rules.json      # Keyword → category rules
│   ├── processing/            # cleaner, merchant, rules, memory, pipeline
│   └── models/                # LightGBM train/predict/registry
├── templates/
│   ├── login.html            # Login form (Jinja)
│   └── register.html         # Registration form (Jinja)
├── static/dist/               # Built React SPA (generated by `npm run build`; gitignored)
├── tests/                    # 451 tests across 18 files (no DB required)
├── Dockerfile                 # Multi-stage: node build → python runtime
├── requirements.txt
└── README.md
```

---

## Checking Cloud Run logs

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="exptrack"' \
  --limit 200 \
  --format "value(textPayload)" \
  --freshness 1d
```
