# CLAUDE.md — ExpTrack

Onboarding guide for AI assistants. Read this at the start of every session.

---

## Project Overview

A production financial pipeline that polls HDFC Bank transaction alert emails daily via the Gmail API, parses 4 email formats (UPI debit old/new, UPI credit, netbanking, debit card), stores parsed transactions in a Neon PostgreSQL database, classifies them into spend categories using a rules → memory → hierarchical LightGBM fallback pipeline, and sends a nightly summary email. Four web UIs are served from the same Cloud Run service: `/review` (batch review of ML predictions), `/view` (full CRUD history editor), `/shared` (shared expense ledger with balance tracking), and `/recurring` (auto-generated monthly expense definitions). These four UIs are a single React SPA (`frontend/`, built into `static/dist`) served by Flask's `spa_catch_all` route in `loader/app.py`; all data access goes through the Flask `/api/*` JSON endpoints. The system runs on Google Cloud Run, is triggered daily at 9 PM IST by Cloud Scheduler, and deploys automatically via GitHub Actions on every push to `main`.

---

## Directory Structure

```
exptrack/
├── loader/                         # Gmail polling + email parsing pipeline + web UIs
│   ├── app.py                      # ENTRY POINT: Flask app, Cloud Run trigger, blueprint registration, spa_catch_all
│   ├── gmail_poller.py             # Gmail polling logic + email parsing (CLI runner)
│   ├── review.py                   # Flask Blueprint: batch review API
│   ├── history.py                  # Flask Blueprint: history viewer/editor API
│   ├── shared.py                   # Flask Blueprint: shared expense ledger API
│   ├── recurring.py                # Flask Blueprint: recurring transactions API
│   ├── token_auth.py               # Auth decorators: require_admin, require_any_auth
│   ├── auth_routes.py              # Flask Blueprint: /login, /logout, /register, /api/me
│   ├── parser.py                   # Email format detection & field extraction
│   ├── db.py                       # PostgreSQL schema creation & queries (9 tables)
│   ├── auth.py                     # One-time OAuth2 setup (run manually once)
│   ├── generate_inserts.py         # Excel → SQL migration utility
│   ├── load_excel.py               # Data feed loading utility
│   ├── backfill_time_period.py     # One-shot: backfill time_period from entry_date for NULL rows
│   └── seed_test_batch.py          # One-shot: inserts a test pending batch for UI testing
│
├── frontend/                       # React + Vite + TypeScript SPA for /review, /view, /shared, /recurring
│   ├── src/pages/                  # Review.tsx, View.tsx, Shared.tsx, Recurring.tsx
│   ├── src/api/                    # Typed fetch wrappers per blueprint (batches, history, shared, recurring)
│   ├── src/hooks/                  # useAuth, useTheme, useToast
│   └── vite.config.ts              # build.outDir → ../static/dist; dev proxy → localhost:8080
│
├── templates/
│   ├── login.html                  # Login form (Jinja, session-based auth)
│   └── register.html               # Registration form (Jinja, requires INVITE_CODE)
│
├── categorizer/                    # Transaction classification pipeline
│   ├── main.py                     # Full training pipeline (run to retrain model)
│   ├── batch_process.py            # ENTRY POINT: batch classification CLI
│   ├── requirements.txt            # Categorizer-specific dependencies
│   ├── config/
│   │   └── rules.json              # Keyword → category mapping rules
│   ├── ingestion/
│   │   ├── database.py             # DB connection & schema queries
│   │   ├── transactions.py         # Batch creation & completion logic
│   │   └── parser.py               # (Minimal use)
│   ├── models/
│   │   ├── train.py                # Hierarchical LightGBM trainer (3-stage)
│   │   ├── predict.py              # 3-stage inference (type → category → subcategory)
│   │   └── registry.py             # GCS joblib model store (save/load champion bundle)
│   ├── processing/
│   │   ├── pipeline.py             # Main prediction orchestration
│   │   ├── cleaner.py              # Text normalization
│   │   ├── rules.py                # Rule-based prediction layer
│   │   ├── memory.py               # Merchant-level prediction cache
│   │   └── merchant.py             # Merchant name extraction
│   ├── evaluation/
│   │   └── metrics.py              # Evaluation metrics
│
├── tests/
│   ├── conftest.py                 # Adds loader/ to sys.path for imports
│   ├── test_parser.py              # 40+ unit tests for email parsing
│   ├── test_gmail_poller.py        # Integration tests (mocked)
│   ├── test_generate_inserts.py    # Migration tool tests
│   ├── test_review.py              # Token auth + /api/categories shape tests
│   └── test_history.py             # History blueprint: auth, periods, pagination, PATCH, DELETE
│
├── .github/
│   └── workflows/
│       └── deploy.yml              # GitHub Actions: test → build → deploy to Cloud Run
│
├── requirements.txt                # Loader dependencies
├── Dockerfile                      # Python 3.12-slim image
├── README.md                       # Deployment & usage guide
├── .env                            # Local secrets (never commit)
└── .gitignore
```

---

## Technical Standards

- **Language:** Python 3.12+
- **HTTP server:** Flask 3.0+ (used only for Cloud Run HTTP trigger mode)
- **Database driver:** `psycopg2-binary` (loader), `psycopg[binary]` async (categorizer)
- **Tests:** pytest — run with `pytest tests/ -v` from repo root
- **Tests must pass before deploy** — CI blocks deployment if any test fails
- **No mocking the database** in tests — tests that require real DB are deferred
- **Containerization:** Docker (Python 3.12-slim base image)
- **Secrets management:** GCP Secret Manager in production; `.env` file locally
- **Two separate `requirements.txt` files:** `requirements.txt` (loader, used by Docker) and `categorizer/requirements.txt` (categorizer, installed manually)

---

## Naming Conventions

### Files
- `snake_case.py` — all Python files: `gmail_poller.py`, `batch_process.py`, `train.py`
- Sub-modules organized by function: `models/`, `processing/`, `ingestion/`, `evaluation/`

### Functions & Methods
- `snake_case`: `get_connection()`, `parse_upi_debit()`, `create_tables()`
- Private helpers prefixed with `_`: `_build_gmail_service()`, `_parse_amount()`
- Format predicates: `is_upi_debit()`, `is_netbanking()`, `is_upi_credit()`
- DB operations: `get_connection()`, `create_tables()`, `is_already_processed()`, `insert_transaction()`

### Classes
- `PascalCase`: `MerchantMemory`, `TransactionParser` (if added)
- Internal/private classes: `_TextExtractor`

### Variables & Constants
- `snake_case` for local and module-level variables: `gmail_message_id`, `transaction_dict`
- `UPPER_CASE` for module-level constants: `HDFC_SENDERS`, `IST`, `GMAIL_SCOPES`, `DEFAULT_RULES_PATH`

### Transaction dict keys (canonical set)
```python
{
    "amount": Decimal,
    "type": "debit" | "credit",
    "format": "upi" | "netbanking" | "debit_card",
    "merchant": str,
    "date": datetime (UTC),
    "vpa": str | None,
    "upi_ref": str | None,
    "account_last4": str | None,
    "card_last4": str | None,
}
```

### Database
- Tables: `snake_case` — `transactions`, `processed_emails`, `transaction_exclusions`, `data_feed_history`, `transaction_batches`, `transaction_batch_items`, `recurring_transactions`, `shared_transactions`, `app_settings`, `users`
- Columns: `snake_case` — `gmail_message_id`, `upi_ref`, `account_last4`, `raw_entry`
- Status enums (stored as VARCHAR): `'success' | 'skipped' | 'failed'` (processed_emails), `'pending' | 'reviewed' | 'complete'` (transaction_batches)
- Prediction source: `'memory' | 'rule' | 'ml' | 'none'`

---

## Key Dependencies

### Loader (`requirements.txt`)
| Package | Version | Purpose |
|---|---|---|
| `flask` | 3.0+ | HTTP server for Cloud Run trigger |
| `google-api-python-client` | 2.132.0 | Gmail API client |
| `google-auth` | 2.29.0 | Google authentication base |
| `google-auth-oauthlib` | 1.2.0 | OAuth2 flow for Gmail access |
| `psycopg2-binary` | 2.9.9 | PostgreSQL sync driver |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `python-dateutil` | 2.9.0.post0 | Date parsing utilities |
| `openpyxl` | 3.1+ | Excel file reading (migration tool) |

### Categorizer (`categorizer/requirements.txt`)
| Package | Purpose |
|---|---|
| `pandas` | DataFrame manipulation for training data |
| `scikit-learn` | TF-IDF vectorization, preprocessing |
| `lightgbm` | Hierarchical 3-stage classifier |
| `google-cloud-storage` | GCS model artifact store |
| `joblib` | Model serialization |
| `psycopg[binary]` | PostgreSQL async driver |
| `python-dotenv` | `.env` file loading |
| `openpyxl` | Excel reading |

---

## Environment Variables

### Loader
| Variable | Required | Description |
|---|---|---|
| `GMAIL_CLIENT_ID` | Yes | OAuth2 client ID from GCP Console |
| `GMAIL_CLIENT_SECRET` | Yes | OAuth2 client secret |
| `GMAIL_REFRESH_TOKEN` | Yes | Long-lived refresh token (generated by `auth.py`) |
| `DATABASE_URL` | Yes | Neon PostgreSQL connection string |
| `NOTIFICATION_EMAIL` | Yes | Recipient for nightly summary email |
| `POLL_DAYS` | No | Days back to search (default: `1`) — ignored if `AFTER_DATE` is set |
| `AFTER_DATE` | No | Gmail `after:` date filter in `YYYY/MM/DD` format; overrides `POLL_DAYS` for backfill runs |
| `MAX_MESSAGES` | No | Cap on messages processed (useful for testing) |
| `PORT` | No | Flask server port (default: `8080`) |
| `ADMIN_TOKEN` | No | If set, admin-only `/api/*` routes (all except `/api/shared/*` and `/api/me`) require this token via `?token=` or `Authorization: Bearer`. The SPA shell itself (`/review`, `/view`, `/recurring`) is always served by `spa_catch_all`; auth is enforced when the page calls the underlying `/api/*` routes. |
| `INVITE_CODE` | No | Required to register a new user at `/register`; must be set to enable user registration |
| `SECRET_KEY` | Prod | Flask session signing key; must be set in production (stored in GCP Secret Manager as `flask-secret-key`). Falls back to `"dev-secret-change-me"` locally with a warning. |
| `GCS_MODEL_BUCKET` | Prod | GCS bucket for ML model artifacts (set to `exptrack-mlruns` in Cloud Run via `deploy.yml`). Required for model retraining triggered by Complete Batch. |

### Categorizer
| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes (or individual vars) | Full Neon connection string |
| `GCS_MODEL_BUCKET` | Yes | GCS bucket name for model storage (`exptrack-mlruns` in production) |
| `DB_HOST` | Alt | Used if `DATABASE_URL` not set |
| `DB_PORT` | Alt | Default: `5432` |
| `DB_NAME` | Alt | Database name |
| `DB_USER` | Alt | Database user |
| `DB_PASSWORD` | Alt | Database password |

---

## Database Schema

### `transactions` — parsed transaction records
```
id               SERIAL PRIMARY KEY
date             TIMESTAMPTZ
amount           NUMERIC(12, 2)
type             VARCHAR(6)          -- 'debit' or 'credit'
format           VARCHAR(20)         -- 'upi', 'netbanking', 'debit_card'
account_last4    CHAR(4)
card_last4       CHAR(4)
vpa              TEXT
merchant         TEXT
raw_entry        TEXT
upi_ref          VARCHAR(30)
gmail_message_id TEXT UNIQUE         -- idempotency key
created_at       TIMESTAMPTZ DEFAULT NOW()
```

### `transaction_exclusions` — transactions removed from review batches
```
transaction_id   INTEGER PRIMARY KEY REFERENCES transactions(id)
excluded_at      TIMESTAMPTZ DEFAULT NOW()
reason           VARCHAR(50) DEFAULT 'user_deleted'
```

### `processed_emails` — audit log for all processed message IDs
```
gmail_message_id TEXT PRIMARY KEY
processed_at     TIMESTAMPTZ
status           VARCHAR(10)         -- 'success', 'skipped', 'failed'
notes            TEXT
```

### `data_feed_history` — labeled training data & final categorized transactions
```
id                    SERIAL PRIMARY KEY
entry_date            DATE NOT NULL
entry_text            TEXT NOT NULL
sub_category          TEXT
category              TEXT
spend_type            VARCHAR(20)         -- 'Expense', 'Investment', 'Saving' (capitalised)
amount                NUMERIC(12, 2) NOT NULL
merchant              TEXT
vpa                   TEXT
upi_ref               TEXT
created_at            TIMESTAMPTZ DEFAULT NOW()
time_period           VARCHAR(10)         -- e.g. 'May-2026', derived from entry_date
cadence               VARCHAR(20) DEFAULT 'O'
divide_by             INTEGER DEFAULT 1
monthly_amount        NUMERIC(12,2)       -- computed: amount / divide_by
shared_expense        CHAR(1) DEFAULT 'N' -- 'Y' or 'N'
share_ratio           NUMERIC(6,4) DEFAULT 1.0
final_amount          NUMERIC(12,2)       -- computed: monthly_amount * share_ratio
exclude_from_training BOOLEAN DEFAULT FALSE  -- TRUE for auto-generated recurring rows
```

### `transaction_batches` — batch lifecycle management
```
id               SERIAL PRIMARY KEY
row_count        INT
status           VARCHAR(20)         -- 'pending', 'reviewed', 'complete'
created_at       TIMESTAMPTZ DEFAULT NOW()
completed_at     TIMESTAMPTZ
```

### `transaction_batch_items` — per-transaction predictions (human-editable)
```
batch_id         INT REFERENCES transaction_batches(id)
transaction_id   INT REFERENCES transactions(id)
pred_category    VARCHAR
pred_subcategory VARCHAR
pred_type        VARCHAR
pred_confidence  DECIMAL(5,4)
pred_source      VARCHAR             -- 'memory', 'rule', 'ml', 'none'
category         VARCHAR             -- editable by human before commit
subcategory      VARCHAR             -- editable by human before commit
type             VARCHAR             -- editable by human before commit
amount           NUMERIC(12,2)       -- can override the transaction amount
cadence          VARCHAR(20) DEFAULT 'O'
divide_by        INTEGER DEFAULT 1
shared_expense   CHAR(1) DEFAULT 'N' -- 'Y' or 'N'
share_ratio      NUMERIC(6,4) DEFAULT 1.0
```

### `recurring_transactions` — auto-generated monthly/annual expense definitions
```
id              SERIAL PRIMARY KEY
entry_text      TEXT NOT NULL
merchant        TEXT
amount          NUMERIC(12, 2) NOT NULL
category        TEXT
sub_category    TEXT
spend_type      VARCHAR(20)
cadence         VARCHAR(20) NOT NULL DEFAULT 'O'
divide_by       INTEGER NOT NULL DEFAULT 1
shared_expense  CHAR(1) NOT NULL DEFAULT 'N'
share_ratio     NUMERIC(6,4) NOT NULL DEFAULT 1.0
active          BOOLEAN NOT NULL DEFAULT TRUE
last_generated  DATE                -- tracks when last auto-generated (idempotency)
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `shared_transactions` — shared expense ledger (mirror of data_feed_history shared rows)
```
id               SERIAL PRIMARY KEY
history_id       INT UNIQUE REFERENCES data_feed_history(id) ON DELETE CASCADE  -- NULL for manual/payment rows
paid_by          TEXT NOT NULL DEFAULT 'Akhil'
owed_by          TEXT NOT NULL DEFAULT 'Aditi'
amount           NUMERIC(12,2) NOT NULL
monthly_amount   NUMERIC(12,2)
share_ratio      NUMERIC(6,4) NOT NULL
akhil_share      NUMERIC(12,2) NOT NULL
aditi_share      NUMERIC(12,2) NOT NULL
balance          NUMERIC(12,2) NOT NULL   -- aditi_share when paid_by='Akhil', akhil_share when paid_by='Aditi'
entry_date       DATE
merchant         TEXT
category         TEXT
subcategory      TEXT
entry_text       TEXT
settled          BOOLEAN NOT NULL DEFAULT FALSE
settled_at       TIMESTAMPTZ
created_at       TIMESTAMPTZ DEFAULT NOW()
is_manual        BOOLEAN NOT NULL DEFAULT FALSE   -- TRUE for manually added rows
is_payment       BOOLEAN NOT NULL DEFAULT FALSE   -- TRUE for settlement payment rows
is_ignored       BOOLEAN NOT NULL DEFAULT FALSE   -- excluded from balance calculations
```

### `app_settings` — configurable UI defaults
```
key        TEXT PRIMARY KEY
value      TEXT NOT NULL
updated_at TIMESTAMPTZ DEFAULT NOW()
```
Default rows: `default_share_ratio = '0.7'`, `default_annual_divisor = '12'`

### `users` — registered user accounts
```
id           SERIAL PRIMARY KEY
username     TEXT UNIQUE NOT NULL
password     TEXT NOT NULL              -- bcrypt hash
role         VARCHAR(10) NOT NULL DEFAULT 'user'  -- 'user' or 'admin'
created_at   TIMESTAMPTZ DEFAULT NOW()
```

**Idempotency:** `processed_emails` tracks every attempted message ID (including failed ones). `transactions` has a UNIQUE constraint on `gmail_message_id`. UPI duplicates are detected by `upi_ref`; others by `(amount, date, format, merchant)`.

**Shared expense scope:** Only `data_feed_history` rows with `entry_date >= 2026-04-01` and `shared_expense = 'Y'` are mirrored to `shared_transactions`. This constant (`_SHARED_SCOPE_START`) is defined once in `db.py` and imported by `review.py` and `history.py`.

**Recurring generation idempotency:** `last_generated` is updated after each generation run. The generation query uses `DATE_TRUNC('month', last_generated)` so re-running on the same day is safe.

---

## Running Tests

```bash
# From repo root
pytest tests/ -v
```

`tests/conftest.py` adds both `loader/` and `categorizer/` to `sys.path`.

**Current test files (451 tests across 18 files, no DB or network required):**

| File | Covers |
|---|---|
| `test_parser.py` | 40+ tests for all 4 email format parsers |
| `test_gmail_poller.py` | `_strip_html`, `_get_received_at`, `_get_subject`, `run_parser_tests`, `run_categorization`, `send_summary_email` |
| `test_generate_inserts.py` | SQL migration utility |
| `test_review.py` | Token auth, `/api/categories` shape, all review API routes (list/get/patch/delete/mark-reviewed/complete/batch-delete) |
| `test_history.py` | Token auth, `/api/history/periods`, `/api/history` pagination, POST create, PATCH update, DELETE, `/api/history/summary`, `/api/settings` GET/PATCH |
| `test_shared.py` | Shared DB functions + all `/api/shared` routes (list, PATCH, DELETE, POST entries, POST payment) + session-based access tests |
| `test_recurring.py` | Auth, all `/api/recurring` routes, `db.generate_recurring_entries` unit tests |
| `test_auth.py` | `/login` GET/POST, `/logout`, `/register` GET/POST — all valid and invalid paths |
| `test_db.py` | `find_duplicate_transaction`, `update_history_row`, `is_already_processed`, `insert_transaction`, `get_history_page`, `get_history_periods`, `delete_history_row`, `log_email`, `insert_data_feed_row`, `get_history_row`, `get_settings`, `update_setting`, `get_history_summary`, `create_user`, `get_user_by_username`, `username_exists` |
| `test_app.py` | Flask trigger route, blueprint wiring, categorization status passthrough to summary email |
| `test_batch_process.py` | Batch pipeline: chunking logic, model load failure, `process_dataframe` call count |
| `test_cleaner.py` | `clean_entry`, `extract_vpa_handle` |
| `test_merchant.py` | `extract_merchant` + stopword list |
| `test_rules.py` | `apply_rules`, Uber amount override |
| `test_memory.py` | `MerchantMemory` lookup/update |
| `test_pipeline.py` | Processing pipeline orchestration |
| `test_train.py` | Model training basics |
| `test_categorizer_db.py` | Categorizer ingestion DB queries |

**Deferred (require real PostgreSQL):** end-to-end pipeline integration, `categorizer/` ML inference against a live DB — do not add database mocks to the test suite.

---

## CI/CD (GitHub Actions)

Workflow: `.github/workflows/deploy.yml` — triggered on push to `main`.

**Job 1 — `test`** (ubuntu-latest):
1. Setup Python 3.12
2. `pip install -r requirements.txt -r categorizer/requirements.txt pytest`
3. `pytest tests/ -v`

**Job 2 — `deploy`** (runs only if `test` passes):
1. Authenticate to GCP via Workload Identity Federation (OIDC)
2. Build Docker image with buildx cache
3. Push to Artifact Registry: `asia-south1-docker.pkg.dev/exptrack-privet-drive/exptrack/exptrack:latest`
4. Deploy to Cloud Run service `exptrack` (region: `asia-south1`)

**Required GitHub secrets:** `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`

---

## Deployment References

- **GCP project:** `exptrack-privet-drive`
- **Cloud Run service:** `exptrack` (region: `asia-south1`)
- **Artifact Registry:** `asia-south1-docker.pkg.dev/exptrack-privet-drive/exptrack/exptrack:latest`
- **Cloud Scheduler job:** `exptrack-daily` — cron `0 21 * * *` (UTC) = 9 PM IST daily
- **Database:** Neon managed PostgreSQL, database name `financial_db`

---

## Development Notes

### Email Parsing Pipeline
`loader/parser.py` detects 4 formats via regex against raw email text:
- `upi_debit` (old format): no VPA in subject
- `upi_debit` (new format): VPA present
- `upi_credit`: credit transactions
- `netbanking`: net banking debits
- `debit_card`: card swipe transactions

Each format has its own `parse_*()` function. The main `parse()` entry point returns a dict or `None`. All dates are stored as UTC. The parser has 40+ unit tests in `tests/test_parser.py` — always run tests after modifying parser logic.

### Categorization Fallback Chain
`categorizer/processing/pipeline.py` applies in order:
1. **Memory** (`memory.py`): exact merchant match from past classifications
2. **Rules** (`rules.py`): keyword match from `config/rules.json`
3. **ML model** (`models/predict.py`): 3-stage LightGBM (type → category → subcategory)
4. **Fallback**: `"Unknown"`

Model bundle is stored in GCS (`GCS_MODEL_BUCKET` env var, path `models/spend-classifier/champion.joblib`). If no model exists in GCS, `batch_process.py` will raise `FileNotFoundError` — run `python main.py` from the `categorizer/` directory with `GCS_MODEL_BUCKET` set to seed it. In Cloud Run, the service account authenticates to GCS automatically via IAM.

**Categorization status in nightly email:** `run_categorization()` in `loader/gmail_poller.py` returns `"ok"` on success or `"FAILED: <reason>"` on exception. This status is passed to `send_summary_email()` and included in a Categorization section in the nightly summary email, making batch failures visible without requiring Cloud Run log access.

**Parser test path fix:** `run_parser_tests()` uses `cwd=os.path.dirname(os.path.abspath(__file__))` so the subprocess resolves `parser.py` relative to `loader/` — required in the Docker container where `WORKDIR=/app` and `parser.py` lives at `/app/loader/parser.py`, not `/app/parser.py`.

### Batch Review Workflow
The old manual SQL approach has been replaced by a web UI. Current workflow:

1. `python categorizer/batch_process.py` — creates batches of up to 25 items each with ML predictions (status: `pending`)
2. Open `/review` in a browser — select the batch from the sidebar
3. Edit `category`, `subcategory`, `type` inline via dropdowns — changes auto-save on every change (PATCH to API)
4. Click **Mark Reviewed** — sets batch status to `reviewed`
5. Click **Complete Batch** — inserts rows into `data_feed_history`, sets status to `complete`, triggers model retraining in background

**Review UI implementation files:**
- `loader/review.py` — Flask Blueprint registered on the main app; all API logic is here
- `frontend/src/pages/Review.tsx` — React page served at `/review` via `loader/app.py`'s `spa_catch_all`
- Blueprint is registered in `loader/app.py` with `app.register_blueprint(review_bp)`

**Review API routes** (all in `loader/review.py`):
| Route | Description |
|---|---|
| `GET /api/batches` | Lists batches; append `?include_complete=1` to include completed ones |
| `GET /api/batches/<id>` | Batch info + all items joined with transactions |
| `PATCH /api/batches/<id>/items/<txn_id>` | Save category/subcategory/type/cadence/divide_by/shared_expense/share_ratio/amount for one item |
| `DELETE /api/batches/<id>/items/<txn_id>` | Remove one item from batch; adds to `transaction_exclusions`, decrements row_count |
| `DELETE /api/batches/<id>` | Delete an entire pending/reviewed batch |
| `POST /api/batches/<id>/mark-reviewed` | Transitions batch pending → reviewed |
| `POST /api/batches/<id>/complete` | Inserts into data_feed_history, mirrors shared rows, triggers retraining |
| `GET /api/categories` | Returns `{categories, types}` merged from rules.json + data_feed_history |

**UI behaviour notes:**
- Category, subcategory, and type use a custom combo: clicking shows a full dropdown, typing filters it, any free-text value is accepted
- Dropdown options are sourced from `GET /api/categories` (merged rules.json + data_feed_history) and populated at page load
- Subcategory options update automatically when category changes
- Input changes fire a PATCH immediately (auto-save, no submit button)
- Orange hint text under an input signals the value differs from the ML prediction
- Revert button (↩) resets all three fields for a row back to ML prediction values
- Delete button (🗑) removes the row from the batch entirely (DELETE API + live row count update)
- Sidebar "Show all" toggle reveals completed batches; selecting a completed batch shows a read-only view with no action buttons
- Complete Batch button is disabled until the batch is marked reviewed
- Column headers for Date, Merchant, Amount, Category, Subcategory, and Type are sortable — click to toggle asc/desc; active sort shown with ▲/▼ icon
- First column is a checkbox for multi-select; header has a select-all checkbox
- A fixed bulk action bar slides up from the bottom when rows are selected; requires all three of category + subcategory + type to be filled before applying bulk edit; also has a bulk delete button
- Complete batches are fully read-only: no checkboxes, no bulk bar, no Mark Reviewed / Complete Batch buttons; the checkbox column is hidden via CSS class `batch-complete` on `<table>`


### History / View Workflow
`/view` is a read/edit UI over `data_feed_history` — the canonical table of categorized and finalized transactions. It complements `/review` (which handles pre-approval batches) by letting the user browse and correct already-committed rows.

**Implementation files:**
- `loader/history.py` — Flask Blueprint registered on the main app; all API logic is here
- `frontend/src/pages/View.tsx` — React page served at `/view` via `loader/app.py`'s `spa_catch_all`
- Blueprint is registered in `loader/app.py` with `app.register_blueprint(history_bp)`

**History API routes** (all in `loader/history.py`):
| Route | Description |
|---|---|
| `GET /api/history/periods` | Distinct time_period values with row counts, newest first |
| `GET /api/history` | Paginated rows for one period (`?period=<p>&page=<n>`), 25 per page |
| `GET /api/history/summary` | Top-5 categories + period total (`?period=<p>&prev_period=<p>` optional) |
| `POST /api/history` | Create a manual entry; cadence=A + divide_by>1 auto-generates future-month rows |
| `PATCH /api/history/<id>` | Update editable fields for one row; returns recomputed amounts |
| `DELETE /api/history/<id>` | Delete a row from data_feed_history |
| `GET /api/settings` | Return `{default_share_ratio, default_annual_divisor}` |
| `PATCH /api/settings` | Update allowed keys (`default_share_ratio`, `default_annual_divisor`) |

**`db.py` functions used by history blueprint:**
- `get_history_periods(conn)` — returns `[{period, count}, ...]`
- `get_history_page(conn, period, page, page_size=25)` — returns `{items, total, page, pages}`
- `get_history_summary(conn, period, prev_period=None)` — returns `{top_categories, period_total}`
- `get_history_row(conn, row_id)` — returns `{id, entry_text, entry_date, time_period}` or None
- `update_history_row(conn, row_id, fields)` — updates and recomputes amounts
- `delete_history_row(conn, row_id)` — deletes row, returns bool
- `get_settings(conn)` — returns `{default_share_ratio: float, default_annual_divisor: int}`
- `update_setting(conn, key, value)` — upserts one setting

**UI behaviour notes:**
- Sidebar lists time periods; selecting one loads 25 rows per page with prev/next pagination
- First column is a row-selection checkbox; header has select-all
- Editing any field marks the row dirty (amber left border) and reveals an **Update** button — **no auto-save**; writes to DB only on explicit Update click
- Computed columns (Mo. Amt, Final Amt) update live in the browser as Divide By / Share Ratio change
- A fixed bulk action bar slides up from the bottom when rows are selected; fill Category + Subcategory + Type, then **Apply to Selected** saves all at once; **Delete Selected** removes rows from DB and table
- Column headers (Period, Date, Merchant, Category, Subcategory, Type, Amount) are sortable client-side
- Combo dropdowns use a single global `<div id="globalDropdown">` at body level (`position: fixed`, `z-index: 9999`), anchored above the input via `transform: translateY(-100%)` — this escapes all ancestor overflow containers
- Settings panel (gear icon) lets the user view/update `default_share_ratio` and `default_annual_divisor` via `/api/settings`

**Backfill:** `loader/backfill_time_period.py` — one-shot script to populate `time_period` from `entry_date` for rows where it is NULL or empty. Run manually if needed.

### Shared Expenses Workflow
`/shared` is a read/edit UI over `shared_transactions` — a ledger that mirrors `data_feed_history` rows where `shared_expense = 'Y'` and `entry_date >= 2026-04-01`.

**Implementation files:**
- `loader/shared.py` — Flask Blueprint; all API logic is here
- `frontend/src/pages/Shared.tsx` — React page served at `/shared` via `loader/app.py`'s `spa_catch_all`

**Mirroring:** Rows are synced automatically in three events:
1. **Complete Batch** (`review.py`) — mirrors qualifying items from batch to `shared_transactions`
2. **PATCH /api/history/<id>** (`history.py`) — upserts or deletes shared row when `shared_expense` changes
3. **POST /api/history** (`history.py`) — inserts shared row if new manual entry is shared
4. **Monthly recurring generation** (`db.generate_recurring_entries`) — mirrors shared recurring rows

**Shared API routes** (all in `loader/shared.py`):
| Route | Description |
|---|---|
| `GET /api/shared/fy-list` | FY start years present in `shared_transactions` |
| `GET /api/shared` | All rows for FY (`?fy=2026`), ordered newest first |
| `GET /api/shared/summary` | `{net_balance, total_akhil_paid, total_aditi_paid}` for FY |
| `POST /api/shared` | Bulk-insert manual entries (array of `{entry_date, monthly_amount, ...}`) |
| `POST /api/shared/payment` | Record a settlement payment (`entry_date`, `paid_by`, `amount` required) |
| `PATCH /api/shared/<id>` | Update `paid_by`/`owed_by`/`share_ratio`/`settled`/`is_ignored`; recomputes balance |
| `DELETE /api/shared/<id>` | Delete a shared row |

**UI behaviour notes:**
- Sidebar: FY selector (e.g. 2026–27); summary cards show net balance, total Akhil paid, total Aditi paid
- Rows styled by type: regular expense, payment (blue), settled (dimmed), ignored (very dimmed)
- Settled toggle auto-saves with timestamp; is_ignored button excludes from balance calculations
- Add entry modal and payment modal for quick manual entry

### Recurring Transactions Workflow
`/recurring` manages definitions of recurring expenses. On the 1st of each month, `app.py` calls `db.generate_recurring_entries()` which inserts one row per active definition into `data_feed_history` (and mirrors to `shared_transactions` if shared).

**Implementation files:**
- `loader/recurring.py` — Flask Blueprint; all API logic is here
- `frontend/src/pages/Recurring.tsx` — React page served at `/recurring` via `loader/app.py`'s `spa_catch_all`

**Recurring API routes** (all in `loader/recurring.py`):
| Route | Description |
|---|---|
| `GET /api/recurring` | List all definitions (active first) |
| `POST /api/recurring` | Create new definition (`entry_text` and `amount` required) |
| `PUT /api/recurring/<id>` | Full update of a definition |
| `DELETE /api/recurring/<id>` | Delete definition |
| `POST /api/recurring/generate` | Manually trigger generation (`?date=YYYY-MM-DD` optional; defaults to today) |

**Generation idempotency:** `last_generated` is stamped after each run. The SELECT query uses `DATE_TRUNC('month', last_generated) < DATE_TRUNC('month', today)` so re-triggering on the same day is safe.

### SPA Serving
`loader/app.py`'s `spa_catch_all` route (`/<path:path>`, registered last) serves the React SPA for everything not explicitly excluded (`api/`, `login`, `logout`, `register`, `trigger`): it serves the matching file from `static/dist` if one exists (built JS/CSS assets), otherwise falls back to `static/dist/index.html` so React Router can handle client-side routing — this covers direct/hard-refresh navigation to `/review`, `/view`, `/shared`, `/recurring`. `static/dist` is produced by `frontend`'s `npm run build` (`vite.config.ts`'s `build.outDir`); the `Dockerfile` runs this in a `node:20-slim` build stage and copies the output into the final image. The Flask app's own `static_folder`/`static_url_path` are left at their defaults (not pointed at `static/dist`) to avoid Werkzeug rule-matching ambiguity between Flask's built-in static route and the catch-all.

The SPA has no client-side route guard — it calls `GET /api/me` on load for display purposes only. Actual authorization is enforced entirely server-side on each `/api/*` call; an unauthenticated user hitting a page sees the shell until the first API call 401s and `frontend/src/api/client.ts` redirects to `/login`.

### Auth System
`loader/token_auth.py` provides two decorators used by blueprints:
- `require_admin` — used by admin `/api/*` routes (batches, history, recurring). Requires `ADMIN_TOKEN` via `?token=` or `Authorization: Bearer`. Dev mode (neither `ADMIN_TOKEN` nor `INVITE_CODE` set): allows all.
- `require_any_auth` — used by `/api/shared/*` routes. Allows either a valid `ADMIN_TOKEN` or a valid user session cookie (role `user` or `admin`).

`loader/auth_routes.py` — `auth_bp` Blueprint:
- `GET/POST /login` — login form (Jinja); sets signed session cookie (30-day expiry) on success, redirects to `/view` (admin) or `/shared` (user)
- `GET /logout` — clears session, redirects to `/login`
- `GET/POST /register` — registration form (Jinja); requires `INVITE_CODE` env var to match
- `GET /api/me` — returns `{username, role}` for the current session/token, or 401; used by the SPA on load

Sessions use Flask's signed cookies with `SECRET_KEY`. No server-side session storage — all Cloud Run instances validate the same cookie using the shared `SECRET_KEY` from GCP Secret Manager.

### SQL Migration Scripts
Never run SQL migration or setup scripts against the database without first asking the user for confirmation and any required inputs (connection strings, target tables, etc.).
