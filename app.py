import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, flash, g, has_request_context, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
DATABASE = os.path.abspath(os.path.join(BASE_DIR, os.environ.get("DATABASE_FILE", "club.db")))
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "development-only-change-me")
app.config["DATABASE"] = DATABASE
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["SUPPORT_EMAIL"] = os.environ.get("SUPPORT_EMAIL", "").strip()
app.config["DEMO_ADMIN_EMAIL"] = os.environ.get("DEMO_ADMIN_EMAIL", "aarav@riverdale.club").strip().lower()
app.config["DEMO_ADMIN_PASSWORD"] = os.environ.get("DEMO_ADMIN_PASSWORD", "admin123")
app.config["DEMO_MEMBER_PASSWORD"] = os.environ.get("DEMO_MEMBER_PASSWORD", "member123")
app.config["COMPANY_ADMIN_EMAIL"] = os.environ.get(
    "COMPANY_ADMIN_EMAIL", "company.admin@commonroom.local"
).strip().lower()
app.config["COMPANY_ADMIN_PASSWORD"] = os.environ.get(
    "COMPANY_ADMIN_PASSWORD", "companyadmin123"
)
app.config["COMPANY_MANAGER_EMAIL"] = os.environ.get(
    "COMPANY_MANAGER_EMAIL", "operations@commonroom.local"
).strip().lower()
app.config["COMPANY_MANAGER_PASSWORD"] = os.environ.get(
    "COMPANY_MANAGER_PASSWORD", "operations123"
)
app.config["COMPANY_SUPPORT_EMAIL"] = os.environ.get(
    "COMPANY_SUPPORT_EMAIL", "support@commonroom.local"
).strip().lower()
app.config["COMPANY_SUPPORT_PASSWORD"] = os.environ.get(
    "COMPANY_SUPPORT_PASSWORD", "support123"
)
ELECTION_TRANSITIONS = {"Draft": {"Open"}, "Open": {"Closed"}, "Closed": set()}


def get_db():
    if "db" not in g:
        try:
            society_id = int(session.get("society_id", 1)) if has_request_context() else 1
        except (TypeError, ValueError) as error:
            raise RuntimeError("Invalid society session.") from error
        if society_id < 1:
            raise RuntimeError("Invalid society session.")
        if society_id == 1:
            database_path = app.config["DATABASE"]
        else:
            database_dir = os.path.join(os.path.dirname(app.config["DATABASE"]), "societies")
            database_path = os.path.join(database_dir, f"society_{society_id}.db")
        g.db = sqlite3.connect(database_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def society_database_path(society_id):
    if society_id == 1:
        return app.config["DATABASE"]
    return os.path.join(
        os.path.dirname(app.config["DATABASE"]),
        "societies",
        f"society_{society_id}.db",
    )


def society_by_code(code):
    normalized_code = str(code or "riverdale-community-club").strip().lower()
    catalog = sqlite3.connect(app.config["DATABASE"])
    catalog.row_factory = sqlite3.Row
    try:
        return catalog.execute(
            "SELECT id,name,slug FROM societies WHERE slug=?",
            (normalized_code,),
        ).fetchone()
    finally:
        catalog.close()


def society_by_id(society_id):
    catalog = sqlite3.connect(app.config["DATABASE"])
    catalog.row_factory = sqlite3.Row
    try:
        return catalog.execute(
            "SELECT id,name,slug FROM societies WHERE id=?",
            (society_id,),
        ).fetchone()
    finally:
        catalog.close()


def activate_society(society_id):
    current_db = g.pop("db", None)
    if current_db is not None:
        current_db.close()
    session["society_id"] = society_id


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def audit(action, entity, entity_id, details):
    get_db().execute("INSERT INTO audit_log (action, entity, entity_id, details) VALUES (?, ?, ?, ?)", (action, entity, entity_id, details))


def valid_email(email):
    local_part, separator, domain = email.partition("@")
    if not separator or "@" in domain or len(local_part) > 64 or len(email) > 254:
        return False
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        return False
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local_part):
        return False
    labels = domain.split(".")
    return len(labels) > 1 and all(
        len(label) <= 63
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
        for label in labels
    )


def valid_date_window(opens, closes):
    try:
        opens_date = date.fromisoformat(opens)
        closes_date = date.fromisoformat(closes)
    except ValueError:
        return False
    return (
        opens_date.isoformat() == opens
        and closes_date.isoformat() == closes
        and opens_date <= closes_date
    )


def init_db(seed=True, connection=None):
    db = connection if connection is not None else get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS societies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        phone TEXT, joined_on TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Active',
        password_hash TEXT, role TEXT NOT NULL DEFAULT 'Member'
    );
    CREATE TABLE IF NOT EXISTS elections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT,
        opens_on TEXT NOT NULL, closes_on TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft'
    );
    CREATE TABLE IF NOT EXISTS nominations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, election_id INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
        member_id INTEGER NOT NULL REFERENCES members(id), role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Approved',
        UNIQUE(election_id, member_id, role)
    );
    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, election_id INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
        voter_id INTEGER NOT NULL REFERENCES members(id), nomination_id INTEGER NOT NULL REFERENCES nominations(id),
        cast_at TEXT NOT NULL, UNIQUE(election_id, voter_id)
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, entity TEXT NOT NULL,
        entity_id INTEGER, details TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS company_employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Active',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    db.execute(
        "INSERT OR IGNORE INTO societies (id,name,slug) VALUES (1,?,?)",
        ("Riverdale Community Club", "riverdale-community-club"),
    )
    society_columns = {row[1] for row in db.execute("PRAGMA table_info(societies)")}
    for column, definition in (
        ("category", "TEXT"),
        ("city", "TEXT"),
        ("address", "TEXT"),
        ("contact_phone", "TEXT"),
        ("member_count_estimate", "INTEGER"),
    ):
        if column not in society_columns:
            db.execute(f"ALTER TABLE societies ADD COLUMN {column} {definition}")
    member_columns = {row[1] for row in db.execute("PRAGMA table_info(members)")}
    if "password_hash" not in member_columns:
        db.execute("ALTER TABLE members ADD COLUMN password_hash TEXT")
    if "role" not in member_columns:
        db.execute("ALTER TABLE members ADD COLUMN role TEXT NOT NULL DEFAULT 'Member'")
    nomination_columns = {row[1] for row in db.execute("PRAGMA table_info(nominations)")}
    if "status" not in nomination_columns:
        db.execute("ALTER TABLE nominations ADD COLUMN status TEXT NOT NULL DEFAULT 'Approved'")
    if seed and db.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0:
        members = [("Aarav Mehta", app.config["DEMO_ADMIN_EMAIL"], "+91 98765 10001", "2024-01-12"), ("Diya Shah", "diya@riverdale.club", "+91 98765 10002", "2024-02-18"), ("Kabir Rao", "kabir@riverdale.club", "+91 98765 10003", "2024-03-03"), ("Meera Iyer", "meera@riverdale.club", "+91 98765 10004", "2024-04-09"), ("Rohan Kapoor", "rohan@riverdale.club", "+91 98765 10005", "2024-05-20")]
        db.executemany("INSERT INTO members (name,email,phone,joined_on) VALUES (?,?,?,?)", members)
        today = date.today()
        db.execute("INSERT INTO elections (title,description,opens_on,closes_on,status) VALUES (?,?,?,?,?)", ("2025 Club Committee", "Choose the committee that will shape the next season.", today.isoformat(), (today + timedelta(days=7)).isoformat(), "Open"))
        election_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.executemany("INSERT INTO nominations (election_id,member_id,role) VALUES (?,?,?)", [(election_id, 1, "President"), (election_id, 2, "President"), (election_id, 3, "Treasurer"), (election_id, 4, "Treasurer")])
        audit("SEEDED", "system", None, "Loaded five members and one sample election")
    if db.execute("SELECT COUNT(*) FROM members WHERE role='Admin'").fetchone()[0] == 0:
        first_member = db.execute("SELECT id FROM members ORDER BY id LIMIT 1").fetchone()
        if first_member:
            db.execute("UPDATE members SET role='Admin' WHERE id=?", (first_member["id"],))
    db.executemany(
        "INSERT OR IGNORE INTO company_employees "
        "(name,email,password_hash,role) VALUES (?,?,?,?)",
        [
            (
                "Company Administrator",
                app.config["COMPANY_ADMIN_EMAIL"],
                generate_password_hash(app.config["COMPANY_ADMIN_PASSWORD"], method="pbkdf2:sha256"),
                "Company Super Admin",
            ),
            (
                "Priya Operations",
                app.config["COMPANY_MANAGER_EMAIL"],
                generate_password_hash(app.config["COMPANY_MANAGER_PASSWORD"], method="pbkdf2:sha256"),
                "Society Manager",
            ),
            (
                "Rohan Support",
                app.config["COMPANY_SUPPORT_EMAIL"],
                generate_password_hash(app.config["COMPANY_SUPPORT_PASSWORD"], method="pbkdf2:sha256"),
                "Support Employee",
            ),
        ],
    )
    members_without_password = db.execute("SELECT id,role FROM members WHERE password_hash IS NULL").fetchall()
    demo_password_hashes = {
        "Admin": generate_password_hash(app.config["DEMO_ADMIN_PASSWORD"], method="pbkdf2:sha256"),
        "Member": generate_password_hash(app.config["DEMO_MEMBER_PASSWORD"], method="pbkdf2:sha256"),
    }
    for member in members_without_password:
        db.execute("UPDATE members SET password_hash=? WHERE id=?", (demo_password_hashes.get(member["role"], demo_password_hashes["Member"]), member["id"]))
    db.commit()


def with_db(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with app.app_context():
            init_db()
            return fn(*args, **kwargs)
    return wrapper


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("member_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def api_login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("member_id"):
            return jsonify(error="Sign in to continue."), 401
        return fn(*args, **kwargs)
    return wrapper


def api_admin_required():
    if session.get("role") != "Admin":
        return jsonify(error="Admin access is required for this action."), 403
    return None


def api_payload():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "Admin":
            flash("Admin access is required for that action.", "error")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapper


def company_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("company_employee_id"):
            return jsonify(error="Company administrator access is required."), 401
        employee = get_db().execute(
            "SELECT role FROM company_employees WHERE id=? AND status='Active'",
            (session["company_employee_id"],),
        ).fetchone()
        if not employee:
            session.pop("company_employee_id", None)
            session.pop("company_role", None)
            return jsonify(error="Company administrator access is required."), 401
        return fn(*args, **kwargs)
    return wrapper


def company_dashboard_endpoint(role):
    role_dashboards = {
        "Company Super Admin": "company_admin_page",
        "Company Admin": "company_admin_page",
        "Society Manager": "company_hr_dashboard",
        "HR": "company_hr_dashboard",
        "Human Resources": "company_hr_dashboard",
        "Support Employee": "company_employee_dashboard",
        "Employee": "company_employee_dashboard",
    }
    return role_dashboards.get(role)


def active_company_employee():
    employee_id = session.get("company_employee_id")
    if not employee_id:
        return None
    company_db = sqlite3.connect(app.config["DATABASE"])
    company_db.row_factory = sqlite3.Row
    try:
        employee = company_db.execute(
            "SELECT id,name,email,role,status,created_at FROM company_employees "
            "WHERE id=? AND status='Active'",
            (employee_id,),
        ).fetchone()
    finally:
        company_db.close()
    if not employee:
        session.pop("company_employee_id", None)
        session.pop("company_role", None)
    return employee


@app.context_processor
def inject_counts():
    if "db" not in g:
        return {"current_user": None}
    db = get_db()
    current_user = None
    if session.get("member_id"):
        current_user = db.execute("SELECT id,name,email,role FROM members WHERE id=? AND status='Active'", (session["member_id"],)).fetchone()
    return {
        "current_user": current_user,
        "member_count": db.execute("SELECT COUNT(*) FROM members WHERE status='Active'").fetchone()[0],
        "open_count": db.execute("SELECT COUNT(*) FROM elections WHERE status='Open'").fetchone()[0],
    }


@app.route("/club")
def club_frontend():
    return render_template("Club/society and club.html")


@app.route("/register-society")
def society_registration_page():
    return render_template(
        "Club/Society Registration.html",
        support_email=app.config["SUPPORT_EMAIL"],
    )


@app.route("/company-admin")
@with_db
def company_admin_page():
    employee = active_company_employee()
    if not employee:
        return redirect(url_for("company_admin_login"))
    dashboard = company_dashboard_endpoint(employee["role"])
    if not dashboard:
        session.pop("company_employee_id", None)
        session.pop("company_role", None)
        flash("Your account does not have a company dashboard. Contact an administrator.", "error")
        return redirect(url_for("company_admin_login"))
    if dashboard != "company_admin_page":
        return redirect(url_for(dashboard))
    catalog = sqlite3.connect(app.config["DATABASE"])
    catalog.row_factory = sqlite3.Row
    try:
        societies = catalog.execute(
            "SELECT id,name,slug,category,city,member_count_estimate,created_at "
            "FROM societies ORDER BY id DESC"
        ).fetchall()
        company_team = catalog.execute(
            "SELECT id,name,email,role,status FROM company_employees "
            "ORDER BY CASE WHEN status='Active' THEN 0 ELSE 1 END, name COLLATE NOCASE"
        ).fetchall()
    finally:
        catalog.close()
    society_rows = []
    recent_activity = []
    live_elections = []
    total_members = 0
    open_elections = 0
    pending_nominations = 0
    unavailable_societies = 0
    today = date.today().isoformat()
    for society in societies:
        database_path = society_database_path(society["id"])
        society_data = dict(society)
        society_db = None
        try:
            if not os.path.isfile(database_path):
                raise sqlite3.OperationalError("Society database file is unavailable.")
            society_db = sqlite3.connect(database_path)
            society_db.row_factory = sqlite3.Row
            member_count = society_db.execute(
                "SELECT COUNT(*) FROM members WHERE status='Active'"
            ).fetchone()[0]
            election_count = society_db.execute(
                "SELECT COUNT(*) FROM elections "
                "WHERE status='Open' AND opens_on<=? AND closes_on>=?",
                (today, today),
            ).fetchone()[0]
            nomination_count = society_db.execute(
                "SELECT COUNT(*) FROM nominations WHERE status='Pending'"
            ).fetchone()[0]
            society_elections = society_db.execute(
                "SELECT e.title,e.closes_on,COUNT(v.id) AS votes "
                "FROM elections e LEFT JOIN votes v ON v.election_id=e.id "
                "WHERE e.status='Open' AND e.opens_on<=? AND e.closes_on>=? "
                "GROUP BY e.id ORDER BY e.closes_on",
                (today, today),
            ).fetchall()
            latest_logs = society_db.execute(
                "SELECT action,details,created_at FROM audit_log "
                "ORDER BY id DESC LIMIT 3"
            ).fetchall()
        except sqlite3.Error:
            member_count = election_count = nomination_count = None
            latest_logs = []
            unavailable_societies += 1
        finally:
            if society_db is not None:
                society_db.close()
        society_data.update(
            members=member_count,
            open_elections=election_count,
            pending_nominations=nomination_count,
            health=(
                "Unavailable" if member_count is None
                else "Needs review" if nomination_count
                else "Operational"
            ),
        )
        society_rows.append(society_data)
        if member_count is not None:
            total_members += member_count
            open_elections += election_count
            pending_nominations += nomination_count
            live_elections.extend(
                {
                    "title": election["title"],
                    "society": society["name"],
                    "closes_on": election["closes_on"],
                    "votes": election["votes"],
                }
                for election in society_elections
            )
        for log in latest_logs:
            recent_activity.append({
                "society": society["name"],
                "action": log["action"],
                "details": log["details"],
                "created_at": log["created_at"],
            })
    recent_activity.sort(key=lambda item: item["created_at"] or "", reverse=True)
    live_elections.sort(key=lambda item: item["closes_on"] or "")
    return render_template(
        "Club/Company Admin .html",
        company_employee=employee,
        dashboard_date=date.today(),
        societies=society_rows,
        recent_activity=recent_activity[:8],
        live_elections=live_elections[:5],
        company_metrics={
            "societies": len(society_rows),
            "members": total_members,
            "open_elections": open_elections,
            "pending_nominations": pending_nominations,
            "unavailable_societies": unavailable_societies,
            "active_team": sum(employee["status"] == "Active" for employee in company_team),
        },
        company_team=company_team,
    )


@app.route("/company-admin/hr")
@with_db
def company_hr_dashboard():
    employee = active_company_employee()
    if not employee:
        return redirect(url_for("company_admin_login"))
    dashboard = company_dashboard_endpoint(employee["role"])
    if dashboard != "company_hr_dashboard":
        if dashboard:
            return redirect(url_for(dashboard))
        session.pop("company_employee_id", None)
        session.pop("company_role", None)
        flash("Your account does not have a company dashboard. Contact an administrator.", "error")
        return redirect(url_for("company_admin_login"))
    company_db = sqlite3.connect(app.config["DATABASE"])
    company_db.row_factory = sqlite3.Row
    try:
        employees = company_db.execute(
            "SELECT id,name,email,role,status,created_at FROM company_employees "
            "ORDER BY name COLLATE NOCASE",
        ).fetchall()
    finally:
        company_db.close()
    employee_rows = [
        {
            "name": row["name"],
            "email": row["email"],
            "role": (
                "HR" if row["role"] in {"Society Manager", "HR", "Human Resources"}
                else "Employee" if row["role"] in {"Support Employee", "Employee"}
                else "Company Admin" if row["role"] in {"Company Super Admin", "Company Admin"}
                else row["role"]
            ),
            "status": row["status"],
        }
        for row in employees
    ]
    return render_template(
        "Club/Company HR.html",
        company_employee=employee,
        employees=employee_rows,
    )


@app.route("/company-admin/employee")
@with_db
def company_employee_dashboard():
    employee = active_company_employee()
    if not employee:
        return redirect(url_for("company_admin_login"))
    dashboard = company_dashboard_endpoint(employee["role"])
    if dashboard != "company_employee_dashboard":
        if dashboard:
            return redirect(url_for(dashboard))
        session.pop("company_employee_id", None)
        session.pop("company_role", None)
        flash("Your account does not have a company dashboard. Contact an administrator.", "error")
        return redirect(url_for("company_admin_login"))
    return render_template(
        "Club/Company Employee.html",
        company_employee=employee,
    )


@app.route("/company-admin/login", methods=["GET", "POST"])
@with_db
def company_admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        company_db = sqlite3.connect(app.config["DATABASE"])
        company_db.row_factory = sqlite3.Row
        try:
            init_db(seed=False, connection=company_db)
            employee = company_db.execute(
                "SELECT id,name,email,role,password_hash FROM company_employees "
                "WHERE email=? AND status='Active'",
                (email,),
            ).fetchone()
        finally:
            company_db.close()
        if not employee or not check_password_hash(employee["password_hash"], password):
            flash("Company email or password is incorrect.", "error")
        else:
            dashboard = company_dashboard_endpoint(employee["role"])
            if not dashboard:
                flash("Your account does not have a company dashboard. Contact an administrator.", "error")
            else:
                session.clear()
                session["company_employee_id"] = employee["id"]
                session["company_role"] = employee["role"]
                return redirect(url_for(dashboard))
    return render_template("Club/Company Admin .html", company_login=True)


@app.route("/company-admin/logout", methods=["POST"])
@with_db
def company_admin_logout():
    session.pop("company_employee_id", None)
    session.pop("company_role", None)
    return redirect(url_for("company_admin_login"))


@app.route("/api/auth", methods=["GET", "POST", "DELETE"])
@with_db
def api_auth():
    db = get_db()
    if request.method == "GET":
        member_id = session.get("member_id")
        if not member_id:
            return jsonify(authenticated=False), 200
        member = db.execute(
            "SELECT id,name,email,role FROM members WHERE id=? AND status='Active'",
            (member_id,),
        ).fetchone()
        if not member:
            session.clear()
            return jsonify(authenticated=False), 200
        return jsonify(authenticated=True, user=dict(member)), 200

    if request.method == "DELETE":
        if session.get("member_id"):
            audit("LOGOUT", "member", session["member_id"], "Signed out")
            db.commit()
        session.clear()
        return jsonify(message="Signed out."), 200

    payload = api_payload()
    action = payload.get("action")
    if action == "login":
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        role = str(payload.get("role", ""))
        society = society_by_code(payload.get("society_code"))
        if not society:
            return jsonify(error="Club code was not found. Check it and try again."), 404
        session.clear()
        activate_society(society["id"])
        db = get_db()
        member = db.execute(
            "SELECT id,name,email,role,password_hash FROM members "
            "WHERE email=? AND status='Active'",
            (email,),
        ).fetchone()
        if not member or not check_password_hash(member["password_hash"], password):
            return jsonify(error="Email or password is incorrect."), 401
        if role != member["role"]:
            return jsonify(error="Choose the account type assigned to this email address."), 403
        session.clear()
        session["society_id"] = society["id"]
        session["member_id"] = member["id"]
        session["role"] = member["role"]
        audit("LOGIN", "member", member["id"], f"Signed in as {member['role']}")
        db.commit()
        return jsonify(
            message="Signed in successfully.",
            user={
                "id": member["id"],
                "name": member["name"],
                "email": member["email"],
                "role": member["role"],
            },
            society={"name": society["name"], "code": society["slug"]},
        ), 200

    if action == "register_club":
        society_name = str(payload.get("society_name", "")).strip()
        category = str(payload.get("category", "")).strip()
        city = str(payload.get("city", "")).strip()
        address = str(payload.get("address", "")).strip()
        contact_phone = str(payload.get("contact_phone", "")).strip()
        member_count = payload.get("member_count_estimate")
        admin_name = str(payload.get("name", "")).strip()
        email = str(payload.get("email", "")).strip().lower()
        confirm_email = str(payload.get("confirm_email", "")).strip().lower()
        phone = str(payload.get("phone", "")).strip()
        password = str(payload.get("password", ""))
        categories = {
            "Student Society",
            "Community Club",
            "Sports Club",
            "Cultural Association",
            "Professional Association",
            "Other",
        }
        if len(society_name) < 2 or len(society_name) > 120:
            return jsonify(error="Society name must be between 2 and 120 characters."), 400
        if category not in categories:
            return jsonify(error="Choose a valid society or club category."), 400
        if len(city) < 2 or len(city) > 100:
            return jsonify(error="Enter a city between 2 and 100 characters."), 400
        if len(address) > 250:
            return jsonify(error="Address must be 250 characters or fewer."), 400
        if contact_phone and (len(contact_phone) > 30 or not re.fullmatch(r"[0-9+(). -]{7,30}", contact_phone)):
            return jsonify(error="Enter a valid society contact phone number."), 400
        try:
            member_count = int(member_count)
        except (TypeError, ValueError):
            return jsonify(error="Enter an estimated member count between 1 and 1,000,000."), 400
        if not 1 <= member_count <= 1_000_000:
            return jsonify(error="Enter an estimated member count between 1 and 1,000,000."), 400
        if not admin_name or not valid_email(email):
            return jsonify(error="Enter the administrator's name and a valid email address."), 400
        if confirm_email != email:
            return jsonify(error="Your email addresses do not match."), 400
        if payload.get("terms_accepted") not in (True, "on", "true", "yes", 1):
            return jsonify(error="Please confirm that you are authorised to register this society."), 400
        if len(password) < 8:
            return jsonify(error="Your password must be at least 8 characters long."), 400
        if password != str(payload.get("confirm_password", "")):
            return jsonify(error="Your passwords do not match."), 400

        slug_base = re.sub(r"[^a-z0-9]+", "-", society_name.lower()).strip("-")
        if not slug_base:
            return jsonify(error="Society name must include letters or numbers."), 400
        previous_session = dict(session)
        catalog = sqlite3.connect(app.config["DATABASE"])
        catalog.row_factory = sqlite3.Row
        database_path = None
        try:
            slug = slug_base
            suffix = 2
            while catalog.execute(
                "SELECT 1 FROM societies WHERE slug=?", (slug,)
            ).fetchone():
                slug = f"{slug_base}-{suffix}"
                suffix += 1
            cursor = catalog.execute(
                "INSERT INTO societies "
                "(name,slug,category,city,address,contact_phone,member_count_estimate) "
                "VALUES (?,?,?,?,?,?,?)",
                (society_name, slug, category, city, address, contact_phone, member_count),
            )
            society_id = cursor.lastrowid
            database_path = society_database_path(society_id)
            os.makedirs(os.path.dirname(database_path), exist_ok=True)
            society_db = sqlite3.connect(database_path)
            try:
                init_db(seed=False, connection=society_db)
            finally:
                society_db.close()

            session.clear()
            activate_society(society_id)
            db = get_db()
            admin_cursor = db.execute(
                "INSERT INTO members (name,email,phone,joined_on,password_hash,role) "
                "VALUES (?,?,?,?,?,'Admin')",
                (
                    admin_name,
                    email,
                    phone,
                    date.today().isoformat(),
                    generate_password_hash(password, method="pbkdf2:sha256"),
                ),
            )
            audit(
                "CLUB_REGISTERED",
                "society",
                society_id,
                f"Created {society_name} ({category}, {city}); registration terms v1 accepted",
            )
            audit("REGISTERED", "member", admin_cursor.lastrowid, f"Registered {admin_name} as Admin")
            db.commit()
            catalog.commit()
        except sqlite3.IntegrityError:
            catalog.rollback()
            session.clear()
            session.update(previous_session)
            if "db" in g:
                g.pop("db").close()
            if database_path and os.path.exists(database_path):
                os.remove(database_path)
            return jsonify(error="This administrator email or club registration already exists."), 409
        except Exception:
            catalog.rollback()
            session.clear()
            session.update(previous_session)
            if "db" in g:
                g.pop("db").close()
            if database_path and os.path.exists(database_path):
                os.remove(database_path)
            raise
        finally:
            catalog.close()
        session["society_id"] = society_id
        session["member_id"] = admin_cursor.lastrowid
        session["role"] = "Admin"
        return jsonify(
            message="Your society is registered. Save its club code for member sign-in.",
            user={"id": admin_cursor.lastrowid, "name": admin_name, "email": email, "role": "Admin"},
            society={"id": society_id, "name": society_name, "code": slug},
        ), 201

    if action == "register":
        name = str(payload.get("name", "")).strip()
        email = str(payload.get("email", "")).strip().lower()
        phone = str(payload.get("phone", "")).strip()
        password = str(payload.get("password", ""))
        role = str(payload.get("role", "Member"))
        if not name or not valid_email(email):
            return jsonify(error="Enter your name and a valid email address."), 400
        if role not in {"Member", "Candidate"}:
            return jsonify(error="Choose Member or Candidate. Admin accounts are assigned by an administrator."), 400
        if len(password) < 8:
            return jsonify(error="Your password must be at least 8 characters long."), 400
        if password != str(payload.get("confirm_password", "")):
            return jsonify(error="Your passwords do not match."), 400
        society = society_by_code(payload.get("society_code"))
        if not society:
            return jsonify(error="Club code was not found. Check it and try again."), 404
        session.clear()
        activate_society(society["id"])
        db = get_db()
        try:
            cursor = db.execute(
                "INSERT INTO members (name,email,phone,joined_on,password_hash,role) "
                "VALUES (?,?,?,?,?,?)",
                (
                    name,
                    email,
                    phone,
                    date.today().isoformat(),
                    generate_password_hash(password, method="pbkdf2:sha256"),
                    role,
                ),
            )
            audit("REGISTERED", "member", cursor.lastrowid, f"Registered {name} as {role}")
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="An account with that email already exists."), 409
        return jsonify(message="Account created. Sign in to continue.", role=role), 201

    return jsonify(error="Choose a supported authentication action."), 400


@app.route("/api/workspace")
@with_db
@api_login_required
def api_workspace():
    db = get_db()
    role = session["role"]
    data = {
        "society": dict(society_by_id(session.get("society_id", 1))),
        "user": dict(db.execute(
            "SELECT id,name,email,role,phone,joined_on FROM members WHERE id=?",
            (session["member_id"],),
        ).fetchone()),
        "stats": {
            "members": db.execute(
                "SELECT COUNT(*) FROM members WHERE status='Active'"
            ).fetchone()[0],
            "elections": db.execute(
                "SELECT COUNT(*) FROM elections WHERE status='Open'"
            ).fetchone()[0],
            "votes": db.execute("SELECT COUNT(*) FROM votes").fetchone()[0],
            "my_votes": db.execute(
                "SELECT COUNT(*) FROM votes WHERE voter_id=?",
                (session["member_id"],),
            ).fetchone()[0],
        },
        "elections": [dict(row) for row in db.execute(
            "SELECT e.id,e.title,e.description,e.opens_on,e.closes_on,e.status,"
            "COUNT(DISTINCT n.id) AS nominations,COUNT(DISTINCT v.id) AS votes "
            "FROM elections e LEFT JOIN nominations n ON n.election_id=e.id "
            "LEFT JOIN votes v ON v.election_id=e.id GROUP BY e.id ORDER BY e.id DESC"
        ).fetchall()],
    }
    ballot = db.execute(
        "SELECT * FROM elections ORDER BY CASE status WHEN 'Open' THEN 0 ELSE 1 END,id DESC LIMIT 1"
    ).fetchone()
    if ballot:
        ballot_data = dict(ballot)
        ballot_data["nominations"] = [dict(row) for row in db.execute(
            "SELECT n.id,n.role,n.status,m.name,COUNT(v.id) AS votes "
            "FROM nominations n JOIN members m ON m.id=n.member_id "
            "LEFT JOIN votes v ON v.nomination_id=n.id "
            "WHERE n.election_id=? GROUP BY n.id ORDER BY n.role,m.name",
            (ballot["id"],),
        ).fetchall()]
        data["ballot"] = ballot_data
    if role == "Admin":
        data["members"] = [dict(row) for row in db.execute(
            "SELECT id,name,email,phone,joined_on,status,role FROM members ORDER BY name"
        ).fetchall()]
        data["audit"] = [dict(row) for row in db.execute(
            "SELECT action,entity,entity_id,details,created_at FROM audit_log ORDER BY id DESC LIMIT 30"
        ).fetchall()]
    elif role == "Candidate":
        data["nominations"] = [dict(row) for row in db.execute(
            "SELECT n.id,n.role,n.status,e.title,e.status AS election_status,"
            "e.opens_on,e.closes_on FROM nominations n "
            "JOIN elections e ON e.id=n.election_id WHERE n.member_id=? "
            "ORDER BY n.id DESC",
            (session["member_id"],),
        ).fetchall()]
    data["vote_history"] = [dict(row) for row in db.execute(
        "SELECT e.title,n.role,m.name AS nominee,v.cast_at FROM votes v "
        "JOIN elections e ON e.id=v.election_id "
        "JOIN nominations n ON n.id=v.nomination_id "
        "JOIN members m ON m.id=n.member_id WHERE v.voter_id=? "
        "ORDER BY v.id DESC LIMIT 10",
        (session["member_id"],),
    ).fetchall()]
    return jsonify(data), 200


@app.route("/api/members", methods=["GET", "POST"])
@with_db
@api_login_required
def api_members():
    db = get_db()
    denied = api_admin_required()
    if denied:
        return denied
    if request.method == "GET":
        query = request.args.get("q", "").strip()
        rows = db.execute(
            "SELECT id,name,email,phone,joined_on,status,role FROM members "
            "WHERE name LIKE ? OR email LIKE ? ORDER BY name",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        return jsonify(members=[dict(row) for row in rows]), 200
    payload = api_payload()
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = str(payload.get("phone", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "Member"))
    if not name or not valid_email(email) or len(password) < 8 or role not in {"Admin", "Member", "Candidate"}:
        return jsonify(error="Enter a name, valid email, password of at least 8 characters, and valid role."), 400
    try:
        cursor = db.execute(
            "INSERT INTO members (name,email,phone,joined_on,password_hash,role) VALUES (?,?,?,?,?,?)",
            (name, email, phone, date.today().isoformat(), generate_password_hash(password, method="pbkdf2:sha256"), role),
        )
        audit("CREATED", "member", cursor.lastrowid, f"Added {name}")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify(error="That email is already registered."), 409
    return jsonify(message="Member added to the register.", id=cursor.lastrowid), 201


@app.route("/api/members/<int:member_id>", methods=["PUT", "DELETE"])
@with_db
@api_login_required
def api_member_detail(member_id):
    denied = api_admin_required()
    if denied:
        return denied
    db = get_db()
    member = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        return jsonify(error="Member not found."), 404
    if request.method == "DELETE":
        if member["id"] == session.get("member_id"):
            return jsonify(error="You cannot deactivate your own administrator account."), 400
        db.execute("UPDATE members SET status='Inactive' WHERE id=?", (member_id,))
        audit("DEACTIVATED", "member", member_id, f"Deactivated {member['name']}")
        db.commit()
        return jsonify(message="Member deactivated."), 200
    payload = api_payload()
    name = str(payload.get("name", member["name"])).strip()
    email = str(payload.get("email", member["email"])).strip().lower()
    phone = str(payload.get("phone", member["phone"] or "")).strip()
    role = str(payload.get("role", member["role"]))
    status = str(payload.get("status", member["status"]))
    if not name or not valid_email(email) or role not in {"Admin", "Member", "Candidate"}:
        return jsonify(error="Enter a name, valid email, and valid role."), 400
    if status not in {"Active", "Inactive"}:
        return jsonify(error="Choose a valid member status."), 400
    try:
        db.execute(
            "UPDATE members SET name=?,email=?,phone=?,role=?,status=? WHERE id=?",
            (name, email, phone, role, status, member_id),
        )
        audit("UPDATED", "member", member_id, f"Updated {name}")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify(error="That email is already registered."), 409
    return jsonify(message="Member updated."), 200


@app.route("/api/elections", methods=["GET", "POST"])
@with_db
@api_login_required
def api_elections():
    db = get_db()
    if request.method == "GET":
        rows = db.execute(
            "SELECT e.*,COUNT(DISTINCT n.id) AS nominations,COUNT(DISTINCT v.id) AS votes "
            "FROM elections e LEFT JOIN nominations n ON n.election_id=e.id "
            "LEFT JOIN votes v ON v.election_id=e.id GROUP BY e.id ORDER BY e.id DESC"
        ).fetchall()
        return jsonify(elections=[dict(row) for row in rows]), 200
    denied = api_admin_required()
    if denied:
        return denied
    payload = api_payload()
    title = str(payload.get("title", "")).strip()
    opens_on = str(payload.get("opens_on", ""))
    closes_on = str(payload.get("closes_on", ""))
    if not title or not valid_date_window(opens_on, closes_on):
        return jsonify(error="Provide a title and valid YYYY-MM-DD dates with opening on or before closing."), 400
    cursor = db.execute(
        "INSERT INTO elections (title,description,opens_on,closes_on) VALUES (?,?,?,?)",
        (title, str(payload.get("description", "")).strip(), opens_on, closes_on),
    )
    audit("CREATED", "election", cursor.lastrowid, f"Created {title}")
    db.commit()
    return jsonify(message="Election created as a draft.", id=cursor.lastrowid), 201


@app.route("/api/elections/<int:election_id>/<action>", methods=["POST"])
@with_db
@api_login_required
def api_election_action(election_id, action):
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()
    if not election:
        return jsonify(error="Election not found."), 404
    payload = api_payload()
    if action == "status":
        denied = api_admin_required()
        if denied:
            return denied
        status = str(payload.get("status", ""))
        if status not in ELECTION_TRANSITIONS.get(election["status"], set()):
            return jsonify(error="Election status must move from Draft to Open, then Open to Closed."), 400
        db.execute("UPDATE elections SET status=? WHERE id=?", (status, election_id))
        audit("STATUS_CHANGED", "election", election_id, f"Set status to {status}")
        db.commit()
        return jsonify(message=f"Election status changed to {status}."), 200
    if action == "nominate":
        if session.get("role") == "Admin":
            try:
                member_id = int(payload.get("member_id", 0))
            except (TypeError, ValueError):
                return jsonify(error="Choose a valid candidate."), 400
        elif session.get("role") in {"Member", "Candidate"}:
            member_id = session["member_id"]
        else:
            return jsonify(error="This account cannot submit nominations."), 403
        position = str(payload.get("role", "")).strip()
        member = db.execute(
            "SELECT id FROM members WHERE id=? AND status='Active'",
            (member_id,),
        ).fetchone()
        if not position or not member:
            return jsonify(error="Choose a valid member and position."), 400
        nomination_status = "Approved" if session["role"] == "Admin" else "Pending"
        try:
            cursor = db.execute(
                "INSERT INTO nominations (election_id,member_id,role,status) VALUES (?,?,?,?)",
                (election_id, member_id, position, nomination_status),
            )
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="This nomination already exists or is incomplete."), 409
        action_name = "NOMINATION_CREATED" if nomination_status == "Approved" else "NOMINATION_SUBMITTED"
        audit(action_name, "election", election_id, f"Member #{member_id} requested {position}")
        db.commit()
        return jsonify(message=f"Nomination {nomination_status.lower()}.", id=cursor.lastrowid), 201
    if action == "vote":
        if session.get("role") not in {"Member", "Candidate"}:
            return jsonify(error="Only member and candidate accounts may vote."), 403
        try:
            nomination_id = int(payload.get("nomination_id", 0))
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid nominee."), 400
        nomination = db.execute(
            "SELECT id FROM nominations WHERE id=? AND election_id=? AND status='Approved'",
            (nomination_id, election_id),
        ).fetchone()
        if election["status"] != "Open":
            return jsonify(error="Voting is closed for this election."), 400
        if not valid_date_window(election["opens_on"], election["closes_on"]):
            return jsonify(error="This election has an invalid voting date window."), 400
        today = date.today()
        if not date.fromisoformat(election["opens_on"]) <= today <= date.fromisoformat(election["closes_on"]):
            return jsonify(error="Voting is outside this election's date window."), 400
        if not nomination:
            return jsonify(error="Choose a valid approved nominee."), 400
        try:
            db.execute(
                "INSERT INTO votes (election_id,voter_id,nomination_id,cast_at) VALUES (?,?,?,?)",
                (election_id, session["member_id"], nomination_id, datetime.now().isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="One vote per member is enforced. This member has already voted."), 409
        audit("VOTED", "election", election_id, f"Vote recorded by member #{session['member_id']}")
        db.commit()
        return jsonify(message="Your vote has been recorded."), 201
    return jsonify(error="Unsupported election action."), 400


@app.route("/api/elections/<int:election_id>", methods=["PUT", "DELETE"])
@with_db
@api_login_required
def api_election_detail(election_id):
    denied = api_admin_required()
    if denied:
        return denied
    db = get_db()
    election = db.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()
    if not election:
        return jsonify(error="Election not found."), 404
    if request.method == "DELETE":
        if election["status"] != "Draft":
            return jsonify(error="Only draft elections can be deleted."), 400
        db.execute("DELETE FROM elections WHERE id=?", (election_id,))
        audit("DELETED", "election", election_id, f"Deleted {election['title']}")
        db.commit()
        return jsonify(message="Draft election deleted."), 200
    payload = api_payload()
    title = str(payload.get("title", election["title"])).strip()
    description = str(payload.get("description", election["description"] or "")).strip()
    opens_on = str(payload.get("opens_on", election["opens_on"]))
    closes_on = str(payload.get("closes_on", election["closes_on"]))
    if election["status"] != "Draft":
        return jsonify(error="Only draft elections can be edited."), 400
    if not title or not valid_date_window(opens_on, closes_on):
        return jsonify(error="Provide a title and valid YYYY-MM-DD dates."), 400
    db.execute(
        "UPDATE elections SET title=?,description=?,opens_on=?,closes_on=? WHERE id=?",
        (title, description, opens_on, closes_on, election_id),
    )
    audit("UPDATED", "election", election_id, f"Updated {title}")
    db.commit()
    return jsonify(message="Election updated."), 200


@app.route("/api/nominations/<int:nomination_id>/<action>", methods=["POST"])
@with_db
@api_login_required
def api_nomination_action(nomination_id, action):
    denied = api_admin_required()
    if denied:
        return denied
    if action not in {"approve", "reject"}:
        return jsonify(error="Unsupported nomination action."), 400
    db = get_db()
    nomination = db.execute(
        "SELECT n.id,n.status,m.name,e.title FROM nominations n "
        "JOIN members m ON m.id=n.member_id JOIN elections e ON e.id=n.election_id "
        "WHERE n.id=?",
        (nomination_id,),
    ).fetchone()
    if not nomination:
        return jsonify(error="Nomination not found."), 404
    status = "Approved" if action == "approve" else "Rejected"
    db.execute("UPDATE nominations SET status=? WHERE id=?", (status, nomination_id))
    audit("NOMINATION_REVIEWED", "nomination", nomination_id, f"{status}: {nomination['name']} for {nomination['title']}")
    db.commit()
    return jsonify(message=f"Nomination {status.lower()}."), 200


@app.route("/api/audit")
@with_db
@api_login_required
def api_audit():
    denied = api_admin_required()
    if denied:
        return denied
    rows = get_db().execute(
        "SELECT action,entity,entity_id,details,created_at FROM audit_log ORDER BY id DESC LIMIT 100"
    ).fetchall()
    return jsonify(events=[dict(row) for row in rows]), 200


@app.route("/login", methods=["GET", "POST"])
@with_db
def login():
    if request.method == "GET" and session.get("member_id"):
        member = get_db().execute(
            "SELECT role FROM members WHERE id=? AND status='Active'",
            (session["member_id"],),
        ).fetchone()
        if member and member["role"] == session.get("role"):
            if member["role"] == "Candidate":
                return redirect(url_for("candidate_panel"))
            return redirect(url_for("dashboard"))
        session.clear()

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        requested_role = request.form.get("role", "")
        society = society_by_code(request.form.get("society_code"))
        if not society:
            flash("Club code was not found. Check it and try again.", "error")
            return render_template("Club/society and club.html", login_page=True)
        session.clear()
        activate_society(society["id"])
        member = get_db().execute(
            "SELECT id,name,email,role,password_hash FROM members WHERE email=? AND status='Active'",
            (email,),
        ).fetchone()
        if not member or not check_password_hash(member["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        elif requested_role != member["role"]:
            flash("Choose the account type assigned to this email address.", "error")
        else:
            session.clear()
            session["society_id"] = society["id"]
            session["member_id"] = member["id"]
            session["role"] = member["role"]
            audit("LOGIN", "member", member["id"], f"Signed in as {member['role']}")
            get_db().commit()
            if member["role"] == "Candidate":
                return redirect(url_for("candidate_panel"))
            return redirect(url_for("dashboard"))
    return render_template("Club/society and club.html", login_page=True)


@app.route("/register", methods=["GET", "POST"])
@with_db
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = request.form.get("role", "Member")
        society = society_by_code(request.form.get("society_code"))
        if not name or not valid_email(email):
            flash("Enter your name and a valid email address.", "error")
        elif not society:
            flash("Club code was not found. Check it and try again.", "error")
        elif role not in {"Member", "Candidate"}:
            flash("Choose a valid account type.", "error")
        elif len(password) < 8:
            flash("Your password must be at least 8 characters long.", "error")
        elif password != confirm_password:
            flash("Your passwords do not match.", "error")
        else:
            session.clear()
            activate_society(society["id"])
            db = get_db()
            try:
                cursor = db.execute(
                    "INSERT INTO members (name,email,phone,joined_on,password_hash,role) VALUES (?,?,?,?,?,?)",
                    (
                        name,
                        email,
                        phone,
                        date.today().isoformat(),
                        generate_password_hash(password, method="pbkdf2:sha256"),
                        role,
                    ),
                )
                audit("REGISTERED", "member", cursor.lastrowid, f"Registered {name} as {role}")
                db.commit()
                flash("Your account is ready. Sign in to continue.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("An account with that email already exists.", "error")
    return render_template("Club/society and club.html", register_page=True)


@app.route("/logout", methods=["POST"])
@with_db
@login_required
def logout():
    audit("LOGOUT", "member", session["member_id"], "Signed out")
    get_db().commit()
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@with_db
@login_required
def dashboard():
    db = get_db()
    if session.get("role") == "Candidate":
        return redirect(url_for("candidate_panel"))
    recent = db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 5").fetchall()
    elections = db.execute("SELECT e.*, COUNT(DISTINCT v.voter_id) AS votes FROM elections e LEFT JOIN votes v ON v.election_id=e.id GROUP BY e.id ORDER BY e.id DESC LIMIT 3").fetchall()
    return render_template("Club/society and club.html", recent=recent, elections=elections, today=date.today())


@app.route("/candidate")
@with_db
@login_required
def candidate_panel():
    if session.get("role") != "Candidate":
        flash("Candidate access is required for that page.", "error")
        return redirect(url_for("dashboard"))
    db = get_db()
    nominations = db.execute(
        "SELECT n.id,n.role,n.status,e.id AS election_id,e.title,e.status AS election_status,"
        "e.opens_on,e.closes_on FROM nominations n JOIN elections e ON e.id=n.election_id "
        "WHERE n.member_id=? ORDER BY e.id DESC,n.id DESC",
        (session["member_id"],),
    ).fetchall()
    elections = db.execute(
        "SELECT id,title,status,opens_on,closes_on FROM elections ORDER BY id DESC"
    ).fetchall()
    return render_template(
        "Club/society and club.html",
        candidate_panel=True,
        nominations=nominations,
        elections=elections,
    )


@app.route("/profile", methods=["GET", "POST"])
@with_db
@login_required
def profile():
    db = get_db()
    member = db.execute(
        "SELECT id,name,email,phone,role,joined_on FROM members WHERE id=? AND status='Active'",
        (session["member_id"],),
    ).fetchone()
    if not member:
        session.clear()
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        if not name or not valid_email(email):
            flash("Enter a name and a valid email address.", "error")
        else:
            try:
                db.execute(
                    "UPDATE members SET name=?,email=?,phone=? WHERE id=?",
                    (name, email, phone, member["id"]),
                )
                audit("PROFILE_UPDATED", "member", member["id"], f"Updated profile for {name}")
                db.commit()
                flash("Your profile has been updated.", "success")
                return redirect(url_for("profile"))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("That email address is already registered.", "error")
    return render_template("Club/society and club.html", profile=member)


@app.route("/candidates")
@with_db
@admin_required
def candidates():
    rows = get_db().execute(
        "SELECT m.id,m.name,m.email,m.status,COUNT(n.id) AS nominations,"
        "SUM(CASE WHEN n.status='Pending' THEN 1 ELSE 0 END) AS pending "
        "FROM members m LEFT JOIN nominations n ON n.member_id=m.id "
        "WHERE m.role='Candidate' GROUP BY m.id ORDER BY m.name"
    ).fetchall()
    return render_template("Club/society and club.html", candidates=rows)


@app.route("/members", methods=["GET", "POST"])
@with_db
@admin_required
def members():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "Member")
        if not name or not valid_email(email) or len(password) < 8 or role not in {"Admin", "Member", "Candidate"}:
            flash("Enter a name, valid email, password of at least 8 characters, and valid role.", "error")
        else:
            try:
                cur = db.execute(
                    "INSERT INTO members (name,email,phone,joined_on,password_hash,role) VALUES (?,?,?,?,?,?)",
                    (name, email, phone, date.today().isoformat(), generate_password_hash(password, method="pbkdf2:sha256"), role),
                )
                audit("CREATED", "member", cur.lastrowid, f"Added {name}")
                db.commit(); flash("Member added to the register.", "success")
            except sqlite3.IntegrityError:
                flash("That email is already registered.", "error")
        return redirect(url_for("members"))
    query = request.args.get("q", "").strip()
    rows = db.execute("SELECT * FROM members WHERE name LIKE ? OR email LIKE ? ORDER BY name", (f"%{query}%", f"%{query}%")).fetchall()
    return render_template("Club/society and club.html", members=rows, query=query)


@app.route("/elections", methods=["GET", "POST"])
@with_db
@login_required
def elections():
    db = get_db()
    if request.method == "POST":
        if session.get("role") != "Admin":
            flash("Only admins can set up elections.", "error")
            return redirect(url_for("elections"))
        title, opens, closes = request.form["title"].strip(), request.form["opens_on"], request.form["closes_on"]
        if not title or not valid_date_window(opens, closes):
            flash("Provide a title and valid YYYY-MM-DD dates with opening on or before closing.", "error")
        else:
            cur = db.execute("INSERT INTO elections (title,description,opens_on,closes_on) VALUES (?,?,?,?)", (title, request.form["description"].strip(), opens, closes))
            audit("CREATED", "election", cur.lastrowid, f"Created {title}"); db.commit(); flash("Election created as a draft.", "success")
        return redirect(url_for("elections"))
    rows = db.execute("SELECT e.*, COUNT(n.id) AS nominations FROM elections e LEFT JOIN nominations n ON n.election_id=e.id GROUP BY e.id ORDER BY e.id DESC").fetchall()
    return render_template("Club/society and club.html", elections=rows)


@app.route("/elections/<int:election_id>", methods=["GET", "POST"])
@with_db
@login_required
def election_detail(election_id):
    db = get_db(); election = db.execute("SELECT * FROM elections WHERE id=?", (election_id,)).fetchone()
    if not election: return "Election not found", 404
    if request.method == "POST":
        action = request.form.get("action")
        if action == "status":
            if session.get("role") != "Admin":
                flash("Only admins can change election status.", "error")
                return redirect(url_for("election_detail", election_id=election_id))
            status = request.form.get("status", "")
            if status == election["status"]:
                flash("Election status is unchanged.", "success")
            elif status not in ELECTION_TRANSITIONS.get(election["status"], set()):
                flash("Election status must move from Draft to Open, then Open to Closed.", "error")
            else:
                db.execute("UPDATE elections SET status=? WHERE id=?", (status, election_id)); audit("STATUS_CHANGED", "election", election_id, f"Set status to {status}")
        elif action == "nominate":
            try:
                if session.get("role") == "Admin":
                    member_id = int(request.form.get("member_id", ""))
                elif session.get("role") in {"Member", "Candidate"}:
                    member_id = session["member_id"]
                else:
                    raise ValueError
                role = request.form.get("role", "").strip()
                if not role: raise ValueError
                nomination_status = "Approved" if session.get("role") == "Admin" else "Pending"
                db.execute(
                    "INSERT INTO nominations (election_id,member_id,role,status) VALUES (?,?,?,?)",
                    (election_id, member_id, role, nomination_status),
                )
                action_name = "NOMINATION_CREATED" if nomination_status == "Approved" else "NOMINATION_SUBMITTED"
                audit(action_name, "election", election_id, f"Member #{member_id} requested {role}")
                flash(
                    "Nomination added to the ballot."
                    if nomination_status == "Approved"
                    else "Nomination submitted for admin approval.",
                    "success",
                )
            except (sqlite3.IntegrityError, ValueError): flash("This nomination already exists or is incomplete.", "error")
        elif action == "approval":
            if session.get("role") != "Admin":
                flash("Only admins can review nominations.", "error")
            else:
                nomination_id = request.form.get("nomination_id", "")
                decision = request.form.get("decision", "")
                if decision not in {"Approved", "Rejected"}:
                    flash("Choose a valid nomination decision.", "error")
                else:
                    cur = db.execute(
                        "UPDATE nominations SET status=? WHERE id=? AND election_id=? AND status='Pending'",
                        (decision, nomination_id, election_id),
                    )
                    if cur.rowcount:
                        audit(f"NOMINATION_{decision.upper()}", "election", election_id, f"{decision} nomination #{nomination_id}")
                        flash(f"Nomination {decision.lower()}.", "success")
                    else:
                        flash("That pending nomination was not found.", "error")
        elif action == "vote":
            try:
                if session.get("role") not in {"Member", "Candidate"}:
                    raise ValueError("Only member and candidate accounts may vote.")
                voter_id = session["member_id"]
                nomination_id = int(request.form["nomination_id"])
                nomination = db.execute("SELECT * FROM nominations WHERE id=? AND election_id=? AND status='Approved'", (nomination_id, election_id)).fetchone()
                if election["status"] != "Open": raise ValueError("Voting is closed for this election.")
                today = date.today()
                opens_on = date.fromisoformat(election["opens_on"])
                closes_on = date.fromisoformat(election["closes_on"])
                if not opens_on <= today <= closes_on: raise ValueError("Voting is outside this election's date window.")
                if not nomination: raise ValueError("Choose a valid nominee.")
                db.execute("INSERT INTO votes (election_id,voter_id,nomination_id,cast_at) VALUES (?,?,?,?)", (election_id, voter_id, nomination_id, datetime.now().isoformat(timespec="seconds"))); audit("VOTED", "election", election_id, f"Vote recorded by member #{voter_id}")
            except sqlite3.IntegrityError: flash("One vote per member is enforced. This member has already voted.", "error")
            except ValueError as error: flash(str(error), "error")
        db.commit()
        return redirect(url_for("election_detail", election_id=election_id))
    nominations = db.execute("SELECT n.*, m.name FROM nominations n JOIN members m ON m.id=n.member_id WHERE election_id=? AND n.status='Approved' ORDER BY role,name", (election_id,)).fetchall()
    pending_nominations = []
    if session.get("role") == "Admin":
        pending_nominations = db.execute("SELECT n.*, m.name FROM nominations n JOIN members m ON m.id=n.member_id WHERE election_id=? AND n.status='Pending' ORDER BY n.id", (election_id,)).fetchall()
    results = db.execute("SELECT n.role,n.id,m.name,COUNT(v.id) votes FROM nominations n JOIN members m ON m.id=n.member_id LEFT JOIN votes v ON v.nomination_id=n.id WHERE n.election_id=? AND n.status='Approved' GROUP BY n.id ORDER BY n.role,votes DESC", (election_id,)).fetchall()
    members = []
    if session.get("role") == "Admin":
        members = db.execute(
            "SELECT id,name FROM members WHERE status='Active' ORDER BY name"
        ).fetchall()
    return render_template(
        "Club/society and club.html",
        election=election,
        nominations=nominations,
        pending_nominations=pending_nominations,
        results=results,
        members=members,
    )


@app.route("/audit")
@with_db
@admin_required
def audit_log():
    return render_template("Club/society and club.html", logs=get_db().execute("SELECT * FROM audit_log ORDER BY id DESC").fetchall())


@app.cli.command("init-db")
def init_command():
    init_db(); print("Database initialized with sample data.")


if __name__ == "__main__":
    with app.app_context(): init_db()
    app.run(debug=True)
