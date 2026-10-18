import sqlite3
from datetime import date, timedelta

import pytest

from app import app, get_db, init_db

@pytest.fixture
def client(tmp_path):
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "test.db"))
    with app.test_client() as client:
        with app.app_context():
            init_db()
        client.post("/login", data={
            "email": "aarav@riverdale.club",
            "password": "admin123",
            "role": "Admin",
        })
        yield client


def sign_in_as_member(client):
    client.post("/logout")
    return client.post("/login", data={
        "email": "diya@riverdale.club",
        "password": "member123",
        "role": "Member",
    })


def test_login_and_register_pages_are_available(client):
    client.post("/logout")
    assert b"Welcome back" in client.get("/login").data
    assert b'name="role"' in client.get("/login").data
    assert b'value="Member">Member' in client.get("/login").data
    assert b'value="Candidate">Candidate' in client.get("/login").data
    assert b'value="Admin">Admin' in client.get("/login").data
    register_page = client.get("/register")
    assert b"Create your account" in register_page.data
    assert b"Create an account" in client.get("/login").data


def test_club_frontend_is_served_by_flask_api(client):
    page = client.get("/club")
    assert page.status_code == 200
    assert b"/api/workspace" in page.data
    assert client.get("/api/workspace").status_code == 200


def test_company_employee_login_opens_role_dashboard_and_logout(client):
    client.post("/logout")
    login_page = client.get("/company-admin")
    assert login_page.status_code == 302
    assert login_page.headers["Location"].endswith("/company-admin/login")
    assert b"Company workspace" in client.get("/company-admin/login").data

    invalid = client.post("/company-admin/login", data={
        "email": "company.admin@commonroom.local",
        "password": "wrong-password",
    })
    assert invalid.status_code == 200
    assert b"Company email or password is incorrect." in invalid.data

    login = client.post("/company-admin/login", data={
        "email": "company.admin@commonroom.local",
        "password": "companyadmin123",
    })
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/company-admin")
    dashboard = client.get("/company-admin")
    assert dashboard.status_code == 200
    assert b"COMPANY SUPER ADMIN" in dashboard.data
    assert b"Company Administrator" in dashboard.data
    assert b"Society portfolio" in dashboard.data
    assert b"Riverdale Community Club" in dashboard.data
    assert b"Registered societies" in dashboard.data
    assert b"Active members" in dashboard.data
    assert b"Recent society activity" in dashboard.data
    assert b"Live elections" in dashboard.data
    assert b"2025 Club Committee" in dashboard.data

    logout = client.post("/company-admin/logout")
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/company-admin/login")


def test_company_admin_dashboard_uses_company_database_from_any_society_session(client, tmp_path):
    (tmp_path / "societies").mkdir(exist_ok=True)
    with client.session_transaction() as session:
        session["society_id"] = 99

    login = client.post("/company-admin/login", data={
        "email": app.config["COMPANY_ADMIN_EMAIL"],
        "password": app.config["COMPANY_ADMIN_PASSWORD"],
    })
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/company-admin")
    with client.session_transaction() as session:
        assert "society_id" not in session

    dashboard = client.get("/company-admin")
    assert dashboard.status_code == 200
    assert b"Riverdale Community Club" in dashboard.data
    assert b"Company Administrator" in dashboard.data


def test_company_dashboard_aggregates_society_members_elections_and_votes(client, tmp_path):
    with app.app_context():
        catalog = get_db()
        society_id = catalog.execute(
            "INSERT INTO societies (name,slug,category,city) "
            "VALUES (?,?,?,?)",
            ("South Ridge Society", "south-ridge-society", "Community Club", "Jaipur"),
        ).lastrowid
        unavailable_id = catalog.execute(
            "INSERT INTO societies (name,slug,category,city) "
            "VALUES (?,?,?,?)",
            ("Harbor Club", "harbor-club", "Community Club", "Mumbai"),
        ).lastrowid
        catalog.commit()

    society_dir = tmp_path / "societies"
    society_dir.mkdir(exist_ok=True)
    society_db = sqlite3.connect(society_dir / f"society_{society_id}.db")
    init_db(seed=False, connection=society_db)
    society_db.execute(
        "INSERT INTO members (name,email,joined_on,status,role) VALUES (?,?,?,?,?)",
        ("Nisha Verma", "nisha@southridge.example", date.today().isoformat(), "Active", "Member"),
    )
    election_id = society_db.execute(
        "INSERT INTO elections (title,opens_on,closes_on,status) VALUES (?,?,?,'Open')",
        ("South Ridge Committee", date.today().isoformat(), (date.today() + timedelta(days=4)).isoformat()),
    ).lastrowid
    nomination_id = society_db.execute(
        "INSERT INTO nominations (election_id,member_id,role,status) VALUES (?,?,?,'Pending')",
        (election_id, 1, "Treasurer"),
    ).lastrowid
    society_db.execute(
        "INSERT INTO votes (election_id,voter_id,nomination_id,cast_at) VALUES (?,?,?,?)",
        (election_id, 1, nomination_id, date.today().isoformat()),
    )
    society_db.commit()
    society_db.close()

    client.post("/company-admin/login", data={
        "email": app.config["COMPANY_ADMIN_EMAIL"],
        "password": app.config["COMPANY_ADMIN_PASSWORD"],
    })
    dashboard = client.get("/company-admin")
    assert dashboard.status_code == 200
    assert b"South Ridge Society" in dashboard.data
    assert b"South Ridge Committee" in dashboard.data
    assert b"Harbor Club" in dashboard.data
    assert b"Some workspace data could not be loaded." in dashboard.data
    assert b"Known members" in dashboard.data
    assert b'<strong class="metric-value">6+</strong>' in dashboard.data
    assert b"1<small>votes</small>" in dashboard.data
    assert b"Needs review" in dashboard.data
    assert b"Unavailable" in dashboard.data
    assert not (society_dir / f"society_{unavailable_id}.db").exists()


def test_company_login_routes_hr_and_employee_to_separate_dashboards(client):
    client.post("/logout")
    hr_login = client.post("/company-admin/login", data={
        "email": app.config["COMPANY_MANAGER_EMAIL"],
        "password": app.config["COMPANY_MANAGER_PASSWORD"],
    })
    assert hr_login.status_code == 302
    assert hr_login.headers["Location"].endswith("/company-admin/hr")

    hr_dashboard = client.get("/company-admin/hr")
    assert hr_dashboard.status_code == 200
    assert b"HUMAN RESOURCES" in hr_dashboard.data
    assert b"Company Administrator" in hr_dashboard.data
    assert b"HR" in hr_dashboard.data
    assert client.get("/company-admin/employee").headers["Location"].endswith("/company-admin/hr")

    client.post("/company-admin/logout")
    employee_login = client.post("/company-admin/login", data={
        "email": app.config["COMPANY_SUPPORT_EMAIL"],
        "password": app.config["COMPANY_SUPPORT_PASSWORD"],
    })
    assert employee_login.status_code == 302
    assert employee_login.headers["Location"].endswith("/company-admin/employee")

    employee_dashboard = client.get("/company-admin/employee")
    assert employee_dashboard.status_code == 200
    assert b"EMPLOYEE WORKSPACE" in employee_dashboard.data
    assert b"Rohan Support" in employee_dashboard.data
    assert b"Company Administrator" not in employee_dashboard.data
    assert client.get("/company-admin/hr").headers["Location"].endswith("/company-admin/employee")


def test_society_registration_creates_an_isolated_admin_workspace(client):
    page = client.get("/register-society")
    assert page.status_code == 200
    assert b"Register a club or society" in page.data
    assert b"Everything your club needs to run well" in page.data
    assert b'href="#features"' in page.data
    assert b"Member dashboard" in page.data
    assert b"Before you begin, have these ready" in page.data
    assert b'href="#register">Register your society' in page.data
    assert b"Privacy overview" in page.data
    assert b"Terms overview" in page.data
    assert b"No support email has been configured" in page.data
    assert b"you\xe2\x80\x99re signed in as Admin" in page.data
    assert b'href="/">Open admin dashboard' in page.data
    assert b'href="/club">Open club portal' in page.data
    assert b"THE COMMON ROOM JOURNAL" in page.data
    assert b"illustrative editorial guides, not testimonials" in page.data
    assert b"Before the first ballot, agree on the rules" in page.data

    client.delete("/api/auth")
    registration = client.post("/api/auth", json={
        "action": "register_club",
        "society_name": "South Ridge Society",
        "category": "Community Club",
        "city": "Jaipur",
        "address": "12 Ridge Road",
        "contact_phone": "+91 98765 00000",
        "member_count_estimate": 120,
        "name": "Nisha Verma",
        "email": "admin@southridge.example",
        "confirm_email": "admin@southridge.example",
        "phone": "",
        "password": "securepass123",
        "confirm_password": "securepass123",
        "terms_accepted": True,
    })
    assert registration.status_code == 201
    code = registration.json["society"]["code"]
    assert code.startswith("south-ridge-society")
    assert registration.json["user"]["role"] == "Admin"
    assert client.get("/api/auth").json == {
        "authenticated": True,
        "user": {
            "id": registration.json["user"]["id"],
            "name": "Nisha Verma",
            "email": "admin@southridge.example",
            "role": "Admin",
        },
    }
    login_page = client.get("/login")
    assert login_page.status_code == 302
    assert login_page.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200
    assert client.get("/club").status_code == 200
    assert client.get("/api/auth").json["authenticated"] is True

    admin_workspace = client.get("/api/workspace")
    assert admin_workspace.json["society"]["name"] == "South Ridge Society"
    assert admin_workspace.json["stats"]["members"] == 1
    assert admin_workspace.json["elections"] == []

    client.delete("/api/auth")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM members").fetchone()[0] == 5
        society = get_db().execute(
            "SELECT category,city,address,contact_phone,member_count_estimate "
            "FROM societies WHERE slug=?",
            (code,),
        ).fetchone()
        assert tuple(society) == (
            "Community Club",
            "Jaipur",
            "12 Ridge Road",
            "+91 98765 00000",
            120,
        )

    client.delete("/api/auth")
    member_registration = client.post("/api/auth", json={
        "action": "register",
        "society_code": code,
        "name": "Kiran Shah",
        "email": "member@southridge.example",
        "role": "Member",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    assert member_registration.status_code == 201
    login = client.post("/api/auth", json={
        "action": "login",
        "society_code": code,
        "email": "member@southridge.example",
        "password": "securepass123",
        "role": "Member",
    })
    assert login.status_code == 200
    assert client.get("/api/workspace").json["stats"]["members"] == 2


def test_society_registration_rejects_invalid_admin_credentials(client):
    response = client.post("/api/auth", json={
        "action": "register_club",
        "society_name": "Example Association",
        "category": "Community Club",
        "city": "Jaipur",
        "member_count_estimate": 20,
        "name": "New Admin",
        "email": "admin@example.org",
        "confirm_email": "admin@example.org",
        "password": "short",
        "confirm_password": "short",
        "terms_accepted": True,
    })
    assert response.status_code == 400
    assert "at least 8 characters" in response.json["error"]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM societies").fetchone()[0] == 1


def test_society_registration_requires_matching_email_and_consent(client):
    base_payload = {
        "action": "register_club",
        "society_name": "Example Association",
        "category": "Community Club",
        "city": "Jaipur",
        "member_count_estimate": 20,
        "name": "New Admin",
        "email": "admin@example.org",
        "confirm_email": "different@example.org",
        "password": "securepass123",
        "confirm_password": "securepass123",
        "terms_accepted": True,
    }
    mismatch = client.post("/api/auth", json=base_payload)
    assert mismatch.status_code == 400
    assert mismatch.json["error"] == "Your email addresses do not match."

    base_payload["confirm_email"] = base_payload["email"]
    base_payload["terms_accepted"] = False
    no_consent = client.post("/api/auth", json=base_payload)
    assert no_consent.status_code == 400
    assert "authorised" in no_consent.json["error"]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM societies").fetchone()[0] == 1


def test_api_auth_rejects_wrong_role_and_workspace_is_database_backed(client):
    client.delete("/api/auth")
    wrong_role = client.post("/api/auth", json={
        "action": "login",
        "email": "diya@riverdale.club",
        "password": "member123",
        "role": "Candidate",
    })
    assert wrong_role.status_code == 403
    assert wrong_role.json["error"]

    login = client.post("/api/auth", json={
        "action": "login",
        "email": "diya@riverdale.club",
        "password": "member123",
        "role": "Member",
    })
    assert login.status_code == 200
    workspace = client.get("/api/workspace")
    assert workspace.json["user"]["role"] == "Member"
    assert workspace.json["stats"]["members"] == 5
    assert workspace.json["ballot"]["title"] == "2025 Club Committee"


def test_api_registration_and_admin_member_creation_are_validated(client):
    client.delete("/api/auth")
    registration = client.post("/api/auth", json={
        "action": "register",
        "name": "Nisha Verma",
        "email": "nisha@example.org",
        "role": "Candidate",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    assert registration.status_code == 201
    assert registration.json["role"] == "Candidate"

    login = client.post("/api/auth", json={
        "action": "login",
        "email": "nisha@example.org",
        "password": "securepass123",
        "role": "Candidate",
    })
    assert login.status_code == 200
    assert client.post("/api/members", json={
        "name": "Unauthorized",
        "email": "no@example.org",
        "password": "securepass123",
    }).status_code == 403

    client.delete("/api/auth")
    client.post("/api/auth", json={
        "action": "login",
        "email": "aarav@riverdale.club",
        "password": "admin123",
        "role": "Admin",
    })
    created = client.post("/api/members", json={
        "name": "New Member",
        "email": "new@example.org",
        "phone": "",
        "password": "securepass123",
        "role": "Member",
    })
    assert created.status_code == 201
    assert client.get("/api/workspace").json["stats"]["members"] == 7


def test_api_candidate_nomination_and_one_vote_are_enforced(client):
    client.delete("/api/auth")
    client.post("/api/auth", json={
        "action": "register",
        "name": "Nisha Verma",
        "email": "nisha@example.org",
        "role": "Candidate",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    client.post("/api/auth", json={
        "action": "login",
        "email": "nisha@example.org",
        "password": "securepass123",
        "role": "Candidate",
    })
    nomination = client.post("/api/elections/1/nominate", json={"role": "Secretary"})
    assert nomination.status_code == 201
    assert nomination.json["message"] == "Nomination pending."

    client.delete("/api/auth")
    client.post("/api/auth", json={
        "action": "login",
        "email": "diya@riverdale.club",
        "password": "member123",
        "role": "Member",
    })
    first_vote = client.post("/api/elections/1/vote", json={"nomination_id": 1})
    duplicate_vote = client.post("/api/elections/1/vote", json={"nomination_id": 2})
    assert first_vote.status_code == 201
    assert duplicate_vote.status_code == 409


def test_member_can_register_with_member_role(client):
    client.post("/logout")
    response = client.post("/register", data={
        "name": "Nisha Verma",
        "email": "nisha@example.org",
        "phone": "",
        "password": "securepass123",
        "confirm_password": "securepass123",
    }, follow_redirects=True)

    assert b"Your account is ready" in response.data
    with app.app_context():
        member = get_db().execute(
            "SELECT role,password_hash FROM members WHERE email=?",
            ("nisha@example.org",),
        ).fetchone()
        assert member["role"] == "Member"
        assert member["password_hash"] != "securepass123"
        assert get_db().execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='REGISTERED'"
        ).fetchone()[0] == 1


def test_candidate_account_opens_candidate_panel_and_tracks_nomination(client):
    client.post("/logout")
    response = client.post("/register", data={
        "name": "Nisha Verma",
        "email": "candidate@example.org",
        "phone": "",
        "role": "Candidate",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    assert response.status_code == 302

    response = client.post("/login", data={
        "email": "candidate@example.org",
        "password": "securepass123",
        "role": "Candidate",
    }, follow_redirects=True)
    assert b"Candidate panel" in response.data
    assert b"Nomination status" in response.data

    response = client.post("/elections/1", data={
        "action": "nominate",
        "role": "Secretary",
    }, follow_redirects=True)
    assert b"Nomination submitted for admin approval." in response.data
    assert b"Secretary" in client.get("/candidate").data


def test_member_profile_updates_and_admin_candidate_register(client):
    response = client.get("/candidates")
    assert response.status_code == 200
    assert b"Candidate register" in response.data

    sign_in_as_member(client)
    response = client.post("/profile", data={
        "name": "Diya Shah",
        "email": "diya.updated@example.org",
        "phone": "+91 90000 00000",
    }, follow_redirects=True)
    assert b"Your profile has been updated." in response.data
    assert b"diya.updated@example.org" in response.data


def test_login_requires_selected_role_to_match_account(client):
    client.post("/logout")
    response = client.post("/login", data={
        "email": "diya@riverdale.club",
        "password": "member123",
        "role": "Candidate",
    }, follow_redirects=True)
    assert b"Choose the account type assigned to this email address." in response.data

    with client.session_transaction() as session:
        assert "member_id" not in session

    member_response = client.post("/login", data={
        "email": "diya@riverdale.club",
        "password": "member123",
        "role": "Member",
    }, follow_redirects=True)
    assert b"Welcome, Diya." in member_response.data
    assert b"Candidate panel" not in member_response.data


def test_each_role_lands_on_its_own_dashboard(client):
    sign_in_as_member(client)
    member_dashboard = client.get("/")
    assert b"MEMBER PORTAL" in member_dashboard.data
    assert b"Candidate panel" not in member_dashboard.data

    client.post("/logout")
    client.post("/register", data={
        "name": "Nisha Verma",
        "email": "candidate@example.org",
        "role": "Candidate",
        "password": "securepass123",
        "confirm_password": "securepass123",
    })
    response = client.post("/login", data={
        "email": "candidate@example.org",
        "password": "securepass123",
        "role": "Candidate",
    }, follow_redirects=True)
    assert b"CANDIDATE / MY ACTIVITY" in response.data
    assert b"Nomination status" in response.data


def test_registration_validates_details_and_duplicate_email(client):
    client.post("/logout")
    invalid_responses = (
        {"name": "New Member", "email": "person@localhost", "password": "securepass123", "confirm_password": "securepass123"},
        {"name": "New Member", "email": "new@example.org", "password": "short", "confirm_password": "short"},
        {"name": "New Member", "email": "new@example.org", "password": "securepass123", "confirm_password": "differentpass"},
        {"name": "New Member", "email": "aarav@riverdale.club", "password": "securepass123", "confirm_password": "securepass123"},
        {"name": "New Member", "email": "new@example.org", "role": "Admin", "password": "securepass123", "confirm_password": "securepass123"},
    )
    for details in invalid_responses:
        response = client.post("/register", data=details, follow_redirects=True)
        assert b"error" in response.data

    with app.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM members"
        ).fetchone()[0] == 5


def test_seeded_dashboard_and_search(client):
    dashboard = client.get("/")
    assert b"Welcome, Aarav." in dashboard.data
    assert b"ADMINISTRATION" in dashboard.data
    assert b"Manage members" in dashboard.data
    response = client.get("/members?q=diya")
    assert b"Diya Shah" in response.data
    assert b"Aarav Mehta" not in response.data

def test_member_email_validation(client):
    for email in ("nope", "person@localhost", "first..last@example.org", "person@-example.org"):
        response = client.post("/members", data={"name": "Bad", "email": email, "phone": ""}, follow_redirects=True)
        assert b"valid email" in response.data
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM members").fetchone()[0] == 5


def test_election_date_window_validation(client):
    today = date.today()
    invalid_windows = (
        ("2026-02-30", "2026-03-01"),
        ("2026-1-2", "2026-01-03"),
        ((today + timedelta(days=1)).isoformat(), today.isoformat()),
    )
    for opens_on, closes_on in invalid_windows:
        response = client.post("/elections", data={
            "title": "Invalid election",
            "opens_on": opens_on,
            "closes_on": closes_on,
            "description": "",
        }, follow_redirects=True)
        assert b"valid YYYY-MM-DD dates" in response.data
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM elections").fetchone()[0] == 1


def test_election_status_transitions_are_forward_only(client):
    today = date.today().isoformat()
    client.post("/elections", data={
        "title": "Transition test",
        "opens_on": today,
        "closes_on": today,
        "description": "",
    })
    with app.app_context():
        election_id = get_db().execute("SELECT id FROM elections WHERE title='Transition test'").fetchone()[0]

    rejected = client.post(f"/elections/{election_id}", data={"action": "status", "status": "Closed"}, follow_redirects=True)
    assert b"must move from Draft to Open" in rejected.data
    client.post(f"/elections/{election_id}", data={"action": "status", "status": "Open"})
    client.post(f"/elections/{election_id}", data={"action": "status", "status": "Closed"})
    rejected = client.post(f"/elections/{election_id}", data={"action": "status", "status": "Open"}, follow_redirects=True)
    assert b"must move from Draft to Open" in rejected.data
    with app.app_context():
        status = get_db().execute("SELECT status FROM elections WHERE id=?", (election_id,)).fetchone()[0]
        assert status == "Closed"

def test_one_vote_per_member(client):
    sign_in_as_member(client)
    first = client.post("/elections/1", data={"action": "vote", "nomination_id": "1"}, follow_redirects=True)
    assert b"Live results" in first.data
    second = client.post("/elections/1", data={"action": "vote", "nomination_id": "2"}, follow_redirects=True)
    assert b"One vote per member" in second.data
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM votes WHERE voter_id=2").fetchone()[0] == 1

def test_closed_election_rejects_vote(client):
    client.post("/elections/1", data={"action": "status", "status": "Closed"})
    sign_in_as_member(client)
    response = client.post("/elections/1", data={"action": "vote", "nomination_id": "1"}, follow_redirects=True)
    assert b"Voting is closed" in response.data

def test_vote_outside_date_window_is_rejected(client):
    with app.app_context():
        get_db().execute("UPDATE elections SET closes_on=? WHERE id=1", ((date.today() - timedelta(days=1)).isoformat(),))
        get_db().commit()
    sign_in_as_member(client)
    response = client.post("/elections/1", data={"action": "vote", "nomination_id": "1"}, follow_redirects=True)
    assert b"date window" in response.data
