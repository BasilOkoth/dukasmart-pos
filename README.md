# DukaSmart POS — Premium Retail Starter (Milestone 1)

A runnable, tenant-isolated retail POS proof of implementation. **No real money transfers or KRA invoices occur.** It includes a premium, responsive retail React PWA with owner overview, cash register, stock management and invoice sandbox screens, FastAPI endpoints, PostgreSQL models, migrations, tests, Docker Compose and a Render Blueprint.

## Included now
- Tenant registration and login, branch creation, isolated products and stock
- Product creation, manual goods received, inventory ledger, checkout with stock decrement
- Decimal-priced sales; product cost/tax snapshot; idempotency key to prevent duplicate checkout
- Cash recording and *simulated* M-Pesa payment status, clearly labelled
- Mock fiscal invoice lifecycle with `NOT_SUBMITTED` and `MOCK_ACKNOWLEDGED` (not actual eTIMS)
- Last 100 sales, mock fiscal monitoring, mobile-responsive web interface
- HTTPS-ready deployment configuration; Alembic schema migration; basic tests

## Start with Docker (recommended)
1. Copy `.env.example` to `.env` in project root; set a long random `JWT_SECRET`.
2. Run `docker compose up --build`.
3. Visit **http://localhost:8080** for the POS; API documentation at **http://localhost:8000/docs**.
4. Register a new business (password >=12 chars). Add product(s) under Products, receive inventory, then complete a simulated checkout under POS.
5. Go to eTIMS tab to inspect pending invoices and mock acknowledgement.

## Start without Docker
Requires Python 3.12+, Node 22+, and PostgreSQL (or SQLite for local tests).
```
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./dukasmart.db
export JWT_SECRET=development-only-secret-longer-than-32-chars
alembic upgrade head
uvicorn app.main:app --reload
```
In a second terminal:
```
cd frontend
npm install
npm run dev
```
Visit http://localhost:5173. Run backend tests with `cd backend && pytest -q`.

## Render
1. Push to a private GitHub repo and create a **Blueprint** from `render.yaml`.
2. Render database and backend use paid plans as written. Review the current Render offering before deploying.
3. Set `CORS_ORIGINS` on the API to the *exact* deployed static-site origin.
4. Set `VITE_API_URL` on the frontend to the *full HTTPS URL* of the API; trigger a **rebuild** because Vite injects it at build time.
5. Ensure strong generated JWT secret and database TLS/network protections.
6. Keep all payment/fiscal methods sandbox/mock until third-party agreements, webhook verification and approvals are complete.

## API surface
`POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/tenants/current`, `GET/POST /api/v1/branches`, `GET/POST /api/v1/products`, `GET /api/v1/inventory?branch_id=...`, `POST /api/v1/inventory/receive`, `POST /api/v1/sales`, `GET /api/v1/sales`, `GET /api/v1/fiscal/invoices`, `POST /api/v1/fiscal/invoices/{sale_id}/simulate`, `GET /api/v1/health`.

## Important limitations before production
- This first milestone is *not a certified eTIMS solution* and cannot issue legal KRA eTIMS receipts. Mock acknowledgement is explicitly not a fiscal success.
- M-Pesa checkout does **not** call Daraja or receive money; it records an intentional simulation. The payment state is `SIMULATED`.
- Cash payment is an operator record, not an independently verified bank transfer.
- No real Daraja callbacks, signature/source validation, merchant credential storage or reconciliation worker yet.
- Frontend currently stores access tokens in sessionStorage for development; production should migrate to a hardened auth model with HttpOnly secure cookies, CSRF defenses, short sessions and MFA.
- Single membership per login in milestone 1; owner + manager/cashier roles are modeled, but user invitations and branch-scoped cashier permissions are pending.
- Basic ledger and stock handling only; returns, refunds, discounts, tax calculations, tax mapping, inventory adjustments, offline persistence, audits, COGS accounting, subscription enforcement, CSV exports and hardware receipt printing are pending.
- Production PostgreSQL transactions use row locks for stocked checkout; SQLite is for simple local development only and is not concurrency-equivalent.
- Concurrent duplicate idempotency requests can race to the unique constraint: the second request may return 409; a future release should retrieve and compare the original payload before returning replay results.
- Do not deploy the provided code without security review, test coverage expansion, rate limiting, monitoring, incident response, and financial/regulatory signoff.

## Next milestones
1. RBAC and invitations; branch-level cashier scopes; session hardening; audit events.
2. Draft checkout/payment intents and asynchronous Daraja **sandbox** STK push + callback verification and reconciliation.
3. Certified eTIMS partner adapter under written integration agreement, partner sandbox contracts, item/tax synchronization and verified fiscal outcomes.
4. Formal finance rules, returns/credit notes, reports, receipt printing, and production release process.

## GitHub upload walkthrough
1. Create a **private** empty GitHub repository (e.g. `dukasmart-pos`).
2. Extract this ZIP locally. Upload the *contents of the `dukasmart-pos` folder* into the root of the repository (`render.yaml`, `backend/`, `frontend/`, etc.). GitHub web UI: **Add file → Upload files → Commit changes**. Alternatively `git init && git add . && git commit -m "DukaSmart starter" && git remote add origin <your-repo-url> && git push -u origin main`.
3. Render: **New → Blueprint**, link the repository, and use the included `render.yaml`. The starter sets non-free example Render service plans; verify cost first.
4. Set backend `CORS_ORIGINS` to exactly your deployed frontend origin (e.g. `https://dukasmart-web.onrender.com`) and frontend `VITE_API_URL` to deployed API origin (e.g. `https://dukasmart-api.onrender.com`); redeploy frontend after setting.
5. Use **demo only** until live API onboarding, role/security hardening and compliance approval.

## Premium UI design
The UI uses responsive emerald/teal styling, modern dashboards, accessible labels, a branch selector, product search, fast quantity adjustments, low-stock indication and prominent sandbox notices. Payment and eTIMS mock operations cannot issue compliant receipts or collect funds.
