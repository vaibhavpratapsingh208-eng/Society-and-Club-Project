# The Common Room

The project uses a modular application package under `app/`, registered
blueprints, SQLAlchemy models, Flask-Migrate, and shared assets under
`static/`. Existing SQLite routes remain available for the current demo while
the PostgreSQL route migration is introduced incrementally. Set `DATABASE_URL`
to configure the SQLAlchemy migration target; do not run a production migration
against the demo database without taking a backup first.

A Flask + SQLite membership and election management app for Project 32: Society/Club Membership and Election Management.

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app run --debug
```

For the SQLAlchemy migration target:

```bash
flask --app app db current
flask --app app db migrate -m "initial relational schema"
flask --app app db upgrade
```

Open `http://127.0.0.1:5000`. The first run seeds five members, one open election, nominations, and an audit event. Data persists in `club.db`.

The premium standalone interface in `.github/society and club.html` is served through Flask at `http://127.0.0.1:5000/club`; open it through this route so its Python-backed login and API requests use the same origin and SQLite database. The detailed club/society information and registration page is at `http://127.0.0.1:5000/register-society`. The VS Code static Live Preview URL does not run Flask or the Python backend.

Set the optional `SUPPORT_EMAIL` environment variable to show a support email link on the society-registration page. If it is not set, the page directs visitors to the operator of that installation. Its privacy and terms sections are informational summaries, not complete legal policies.

## Included workflows

- Public sign-in with an explicit Member/Candidate/Admin account-type choice and role-based registration for Member and Candidate accounts (Admin is assigned only by an existing administrator).
- Club/society onboarding collects the organisation type, location, contact phone, and estimated membership; records registration consent; creates the first administrator; generates a club code; and provisions a separate SQLite database per society. Email is confirmed by re-entry but is not verified by email or OTP.
- Separate member and candidate dashboards, candidate nomination tracking, and a personal profile page.
- Admin candidate register and nomination approval controls, alongside election setup and status management.
- Company super-admin founder dashboard with cross-society member and election totals, live ballot activity, nomination review counts, workspace health, recent audit events, team access, and onboarding shortcuts.
- Member register with duplicate-email and strict email-format validation.
- Search members by name or email.
- Draft election creation with strict ISO date parsing and date-window validation.
- Add nominations by role and move elections forward from Draft to Open to Closed.
- Record votes with SQLite transaction-backed `UNIQUE(election_id, voter_id)` enforcement.
- Live results grouped by role and nominee.
- Audit trail for seed, creation, status changes, nominations, and votes.
- Responsive UI suitable for a short live demo.

## Tests

```bash
pytest -q
```

The tests cover seeded data, member search, malformed email and election dates, allowed election status transitions, one-vote-per-member behavior, closed-election rejection, company role routing, and cross-society founder dashboard aggregation.

## 5-8 minute demonstration

1. **Sign in and registration (45 sec):** Open `/login` or `/register`; create a member account or use the seeded demo credentials configured in `.env`.
2. **Overview (45 sec):** Show dashboard stats, the current election, and recent audit activity.
3. **Members (60 sec):** Search for `diya`, add a member, then submit a malformed email such as `person@localhost` to show validation.
4. **Election setup (90 sec):** Create a draft election with valid dates, try an impossible date such as `2026-02-30`, then add nominations and move the election to Open.
5. **Status and voting (90 sec):** Demonstrate Draft → Open → Closed, record a member vote, and show one-vote protection.
6. **Transparency and tests (60 sec):** Open Audit log, then run `pytest -q` to show the validation, transition, and voting tests pass.
