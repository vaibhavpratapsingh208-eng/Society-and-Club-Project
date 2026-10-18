"""SQLAlchemy model definitions for the PostgreSQL migration.

The running demo still uses the legacy SQLite schema. These models document the
target relational schema and can be enabled when the route layer is migrated.
"""

from .extensions import db


if db is not None:
    class Society(db.Model):
        __tablename__ = "societies"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        slug = db.Column(db.String(140), nullable=False, unique=True)
        category = db.Column(db.String(80))
        city = db.Column(db.String(100))
        address = db.Column(db.String(250))
        contact_phone = db.Column(db.String(30))
        member_count_estimate = db.Column(db.Integer)
        created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


    class Member(db.Model):
        __tablename__ = "members"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        email = db.Column(db.String(254), nullable=False, unique=True)
        phone = db.Column(db.String(30))
        joined_on = db.Column(db.Date, nullable=False)
        status = db.Column(db.String(20), nullable=False, default="Active")
        password_hash = db.Column(db.String(255))
        role = db.Column(db.String(20), nullable=False, default="Member")


    class Election(db.Model):
        __tablename__ = "elections"

        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(160), nullable=False)
        description = db.Column(db.Text)
        opens_on = db.Column(db.Date, nullable=False)
        closes_on = db.Column(db.Date, nullable=False)
        status = db.Column(db.String(20), nullable=False, default="Draft")


    class Nomination(db.Model):
        __tablename__ = "nominations"
        __table_args__ = (
            db.UniqueConstraint("election_id", "member_id", "role"),
        )

        id = db.Column(db.Integer, primary_key=True)
        election_id = db.Column(db.Integer, db.ForeignKey("elections.id", ondelete="CASCADE"), nullable=False)
        member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
        role = db.Column(db.String(80), nullable=False)
        status = db.Column(db.String(20), nullable=False, default="Approved")


    class Vote(db.Model):
        __tablename__ = "votes"
        __table_args__ = (
            db.UniqueConstraint("election_id", "voter_id"),
        )

        id = db.Column(db.Integer, primary_key=True)
        election_id = db.Column(db.Integer, db.ForeignKey("elections.id", ondelete="CASCADE"), nullable=False)
        voter_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
        nomination_id = db.Column(db.Integer, db.ForeignKey("nominations.id"), nullable=False)
        cast_at = db.Column(db.DateTime, nullable=False)


    class AuditLog(db.Model):
        __tablename__ = "audit_log"

        id = db.Column(db.Integer, primary_key=True)
        action = db.Column(db.String(50), nullable=False)
        entity = db.Column(db.String(50), nullable=False)
        entity_id = db.Column(db.Integer)
        details = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


    class CompanyEmployee(db.Model):
        __tablename__ = "company_employees"

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(120), nullable=False)
        email = db.Column(db.String(254), nullable=False, unique=True)
        password_hash = db.Column(db.String(255), nullable=False)
        role = db.Column(db.String(50), nullable=False)
        status = db.Column(db.String(20), nullable=False, default="Active")
        created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
