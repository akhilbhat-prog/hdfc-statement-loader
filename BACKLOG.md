# Backlog

## BL-1 — Fix filter repaging (`/view`)

**Status:** Complete (verified 2026-05-28 — filter correctly resets to page 1 and repaginates from the full in-memory dataset)

---

## BL-2 — User test: sort across pages (`/view`)

**Status:** Complete (verified 2026-05-28 — sort applies to full in-memory dataset and repaginates correctly)

---

## BL-3 — Multi-period Add Entry for Cadence = A (`/view`)

**Status:** Complete (2026-05-28)

When adding an entry with cadence=A and divide_by=N, the backend now creates N rows automatically: the first with the user's entered date (current period), and the remaining N-1 with entry_date set to the 1st of each subsequent month. All rows are independent — editing or deleting one does not affect the others. Toast confirms "N entries added (N months)".

---

## BL-4 — Backfill shared & amortised rows from April 2025

**Status:** Complete (2026-06-07)

User added and edited shared and amortised transactions dating back to April 2025 via `/view`.

---

## BL-5 — Configurable share ratio and annual divisor defaults

**Status:** Complete (2026-06-06)

The default share ratio (0.7) and annual cadence divisor (12 for cadence A) are hardcoded in the UI. Make them user-configurable — either via a settings table in the DB, a config file, or a settings endpoint — so the user can change them without a code deploy.

---

## BL-6 — Shared transaction mirror table

**Status:** Complete (2026-06-06)

Transactions in `data_feed_history` marked `shared_expense = 'Y'` with `entry_date >= 2026-04-01` are automatically mirrored into `shared_transactions`. The mirror syncs on Complete Batch (`/review`), Update (`/view` PATCH), Add Entry (`/view` POST), and monthly recurring generation. A new `/shared` page shows shared rows grouped by financial year (Apr–Mar) with summary cards and a filterable/sortable table. Paid By and Owed By default to Akhil/Aditi (editable). Balance = paid amount minus the payer's own share. Settled checkbox auto-saves with timestamp.

---

## BL-7 — Project description audit

**Status:** Complete (2026-06-14)

Full codebase audit completed. Produced an accurate description covering all 4 UI pages, 9 DB tables, all blueprint routes (review, history, shared, recurring), shared expense mirroring, recurring generation, and the ML categorisation pipeline. The description was further updated during BL-13 to include the auth system (users table, auth_routes.py, token_auth.py, login/register templates).

---

## BL-8 — Update markdown docs

**Status:** Complete (2026-06-14, updated during BL-13)

`README.md` fully rewritten to reflect the current 4-UI system. `CLAUDE.md` updated with: new blueprints (shared.py, recurring.py, auth_routes.py), new templates (shared.html, recurring.html, login.html, register.html), `token_auth.py` with three auth decorators, all 9 DB tables plus the new `users` table, full API route tables for all blueprints, Auth System section covering the two-role design, env vars table updated (REVIEW_TOKEN removed; ADMIN_TOKEN, INVITE_CODE, SECRET_KEY added), updated test count (450 tests across 18 files).

---

## BL-9 — Code refactor review

**Status:** Complete (2026-06-14, extended during BL-13)

Initial refactor: extracted duplicated `_require_token` decorator from all 4 blueprints into `loader/token_auth.py`, and consolidated `_SHARED_SCOPE_START` to a single definition in `db.py`. Extended during BL-13: `token_auth.py` replaced `require_token` with three distinct decorators — `require_admin` (admin token only), `require_any_auth` (admin token or user session), `require_user_page` (same but redirects to `/login` instead of 401). All blueprint imports updated. `REVIEW_TOKEN` references removed from all files.

---

## BL-10 — Expand test coverage

**Status:** Complete (2026-06-14, extended during BL-13)

Initial expansion: 16 new tests in test_db.py and test_history.py covering `get_history_row`, `get_settings`, `update_setting`, `get_history_summary`, and the `GET /api/history/summary` route. Extended during BL-13: new `tests/test_auth.py` (18 tests for /login, /logout, /register), session-based access tests added to test_shared.py, user DB function tests added to test_db.py (create_user, get_user_by_username, username_exists), redirect tests added to test_app.py, `/trigger` protection test added. All REVIEW_TOKEN references replaced with ADMIN_TOKEN across test_review.py, test_history.py, test_recurring.py, test_shared.py, test_app.py. Total test count: 450 across 18 files.

---

## BL-11 — Add new categorisation rules

**Status:** Complete (2026-06-20)

Analysed 1599 distinct entry/category combinations from `data_feed_history`. Added 17 new rules to `categorizer/config/rules.json`: Spotify, Third Wave Coffee, Big Box Cleaners, SSSPCT Aryamba (medical clinic), Medplus, Jio Postpaid, Sandhya Srihari (family transfer), BMRCL (metro), Decathlon, Starbucks, BigBasket, Wow Momo, Uber Eats (specific rule before the generic `uber`), FanCode, Apple Services (billdesk variant), Google Cloud, ACKO (bike insurance). Total rules: 104 (was 83).

---

## BL-12 — Review entries conflicting with rules

**Status:** Complete (2026-06-20, extended 2026-06-20)

Phase 1: Fixed 12 rule conflicts — LIC subcategory → LIC; `reliance` narrowed to `reliance jio`; `HOTEL` rule removed (too broad). Rules for By2Coffee / J B Bekary / Akshaya Enterprises / Md Lalu / Sri Maruthi Dose Cam / Polar Bear / comdyna / Magic / blinkit / Village Hyper Bazaar reverted to match historical data.

Phase 2: Rules confirmed correct; 30 DB entries corrected to match rules — Uber (13 rows: Cab/Metro → Auto), Zomato (5 rows: Eating Out → Ordering In), Magic Time Pass (6 rows: Eating Out → Ordering In), blinkit (2 rows: Food → Misc), Village Hyper Bazaar (4 rows: Food → Misc). Removed 4 overly broad person-name rules (lakshmi, N VENKATESH, S P PRAKASH, PRABHAN). blinkit and Village Hyper Bazaar rules confirmed as Misc/Groceries. ACT rules (ACT BROADBAND, ATRIA CONVERGENCE → Bills/ACT Internet) confirmed correct.

---

## BL-13 — Role-based auth (admin / user)

**Status:** Complete (2026-06-20)

Replaced `REVIEW_TOKEN` with a two-role system. Admin (Akhil) registers at `/register` with `INVITE_CODE` and role promoted to `admin` in DB; logs in at `/login` and gets full session access to all pages without needing `?token=`. User (Aditi) logs in and gets access to `/shared` only. The `/` route acts as a smart redirect. Pipeline moved from `GET /` to `GET /trigger`. `require_admin` accepts both `ADMIN_TOKEN` Bearer token and `role=admin` session. GCP secrets created: `flask-secret-key`, `invite-code`, `admin-token`. Cloud Scheduler updated to `/trigger?token=...`. Smoke tested: admin login → `/view`, user login → `/shared`, cross-access blocked.

---

## BL-16 — Navigation bar across all pages

**Status:** Complete (2026-06-20)

Consistent nav bar added to all four UI pages. Admin pages show links to all four pages; `/shared` shows only the Shared link for user-role sessions. Token query string (`?token=`) is appended automatically for token-based access. Active page is highlighted. Logout button on every page with confirmation dialog.

---

## BL-17 — Show logged-in user and logout button on all pages

**Status:** Complete (2026-06-20)

User chip (teal pill badge) showing `session["username"]` or "Guest" displayed in the header of all four pages. Logout button hits `GET /logout`. Implemented together with BL-16.

---

## BL-14 — Rename the project

**Status:** Complete (2026-06-20)

Renamed to **ExpTrack**. Updated: UI page titles and logo branding (all 4 templates: FinTrack → ExpTrack), `deploy.yml` (service `exptrack`, image `exptrack:latest`), `CLAUDE.md`, `README.md`. GCP project ID (`hdfc-statement-loader`) is immutable and stays unchanged. All GCP steps complete: GitHub repo renamed to `exptrack`, WIF IAM binding updated to `akhilbhat-prog/exptrack`, Cloud Scheduler job updated to point to `exptrack` service URL, old `hdfc-statement-loader` Cloud Run service deleted.

---

## BL-19 — Rename Cloud Scheduler job to exptrack-daily

**Status:** Complete (2026-06-20)

Deleted `hdfc-statement-loader-daily`, recreated as `exptrack-daily` with same settings (frequency `0 21 * * *`, timezone Asia/Calcutta, URL `https://exptrack-1527779814.asia-south1.run.app/trigger?token=admin-tok`, OIDC auth via `hdfc-loader-invoker` service account). Force run confirmed success.

---

## BL-20 — Rename GCS ML model bucket

**Status:** Complete (2026-06-20)

Created `exptrack-mlruns` bucket in `exptrack-privet-drive`, copied `models/spend-classifier/champion.joblib` from `hdfc-statement-loader-mlruns`, granted default compute SA `roles/storage.objectAdmin`. Added `GCS_MODEL_BUCKET=exptrack-mlruns` to `deploy.yml` `--set-env-vars` so it is set on every future deploy. Old bucket `hdfc-statement-loader-mlruns` can be deleted once the old project is decommissioned (BL-18 Phase 11).

---

## BL-18 — Migrate GCP project to new project ID

**Status:** Complete (2026-06-20)

Migrated from `hdfc-statement-loader` to `exptrack-privet-drive` (ID `exptrack` was taken). All resources recreated: Artifact Registry (`exptrack` repo), Secret Manager (7 secrets), service accounts (`github-actions`, default compute), Workload Identity Federation (pool + provider + IAM binding for `akhilbhat-prog/exptrack`), Cloud Run service `exptrack`, Cloud Scheduler job `exptrack-daily`. `deploy.yml` updated with new project and registry paths. Several issues resolved during migration: WIF attribute condition required, `iam.serviceaccounts.actAs` permission needed, secrets had trailing newlines from pipe-copy (fixed with `echo -n` / `tr -d '\n\r'`), `ADMIN_TOKEN` comparison now strips whitespace in `token_auth.py`. Cloud Scheduler force run confirmed Success. Phase 11 (decommission old project) deferred until after one successful nightly run.

---

## BL-21 — Fix GCS_MODEL_BUCKET not surviving Cloud Run deployments

**Status:** Complete (2026-06-27)

Added a dedicated `gcloud run services update` shell step after the `deploy-cloudrun@v2` action. All attempts to set it via the action itself (flags, env_vars param, --set-env-vars, --update-env-vars) silently dropped the variable. The explicit gcloud step mirrors the manual command that was confirmed to work. Verified via `gcloud run services describe` after deploy.

---

## BL-22 — Add "Run Pipeline" trigger button to `/review`

**Status:** Complete (2026-06-27)

Added "Run Pipeline" button to the `/review` sidebar footer. Calls `POST /trigger`, shows a loading state, then displays processed/skipped/failed counts inline. Reloads the batch list on completion so new batches appear immediately.

---

## BL-23 — Rename "History" label to "View" across the UI

**Status:** Complete (2026-06-27)

Updated all four templates: nav link label "History" → "View", `view.html` page title and logo subtitle updated to match.

---

## BL-26 — Include merchant details for skipped messages in summary email

**Status:** Complete (2026-06-27)

Added `get_transaction_by_message_id` to `db.py`. For "already processed" skips, the poller now looks up the transaction and attaches merchant/amount/type to the skipped entry. Email shows e.g. `id=19f0695d3f45c9c4  already processed  (Swiggy  Rs. 350.00  debit)`.

---

## BL-24 — Migrate frontend to React

**Status:** Open

Replace the four vanilla HTML/CSS/JS templates (`review.html`, `view.html`, `shared.html`, `recurring.html`) with a Vite/React app that calls the existing Flask `/api/*` routes. Flask backend stays unchanged — Python ML/Gmail/parsing code is unaffected. React build either served from Flask (static files) or deployed separately. Auth flow (session cookie + admin token) must be preserved.

---

## BL-25 — Decommission old GCP project and remove all HDFC references

**Status:** Complete (2026-06-27)

- GCS bucket `hdfc-statement-loader-mlruns` deleted (confirmed 404)
- GCP project `hdfc-statement-loader` marked `DELETE_REQUESTED` (permanent deletion after 30-day hold)
- Code: docstrings updated, email subjects renamed to "ExpTrack Pipeline Run", README rewritten, stale Artifact Registry path in CLAUDE.md fixed
- Functional HDFC references (HDFC_SENDERS, parser regex, merchant stopword, rules.json) kept — they refer to the bank, not the old project

---

## BL-15 — Context management strategy

**Status:** Complete (2026-06-20)

Audited CLAUDE.md and all memory files. Fixed: added `users` table to DB schema, added `GCS_MODEL_BUCKET` to Loader env vars table, updated categorizer bucket example from `hdfc-statement-loader-mlruns` to `exptrack-mlruns`. Updated 3 stale memory files: `reference_cloud_run_url.md` (new service URL), `project_cicd_backlog.md` (new project/repo/registry references), `project_test_backlog.md` (450 tests, deferred list trimmed). Updated `MEMORY.md` index hooks.
