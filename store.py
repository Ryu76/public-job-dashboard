from __future__ import annotations

import json
import sqlite3
from pathlib import Path

JOB_COLUMNS = [
    "external_id", "title", "organization", "location", "employment_type", "posted_date", "close_date",
    "d_day", "source_status", "source_url", "ncs", "education", "work_field", "hire_type", "replacement",
    "headcount", "preferred", "period_start", "period_end", "salary_reference_url", "monthly_fixed_pay",
    "salary_year", "annual_base_pay", "annual_fixed_allowance", "salary_kind", "salary_note",
    "process_steps", "attachments", "apply_url", "collected_at",
]
JSON_COLUMNS = {"process_steps", "attachments"}


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    external_id TEXT PRIMARY KEY, title TEXT NOT NULL, organization TEXT NOT NULL,
                    location TEXT, employment_type TEXT, posted_date TEXT, close_date TEXT, d_day TEXT,
                    source_status TEXT, source_url TEXT, ncs TEXT, education TEXT, work_field TEXT,
                    hire_type TEXT, replacement TEXT, headcount INTEGER, preferred TEXT, period_start TEXT,
                    period_end TEXT, salary_reference_url TEXT, monthly_fixed_pay INTEGER,
                    salary_year INTEGER, annual_base_pay INTEGER, annual_fixed_allowance INTEGER, salary_kind TEXT,
                    salary_note TEXT,
                    process_steps TEXT DEFAULT '[]', attachments TEXT DEFAULT '[]', apply_url TEXT, collected_at TEXT
                );
                CREATE TABLE IF NOT EXISTS applications (
                    job_id TEXT PRIMARY KEY REFERENCES jobs(external_id) ON DELETE CASCADE,
                    status TEXT NOT NULL, notes TEXT DEFAULT '', next_action_date TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS saved_filters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, criteria TEXT NOT NULL
                );
            """)
            existing = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            migrations = {
                "salary_year": "INTEGER",
                "annual_base_pay": "INTEGER",
                "annual_fixed_allowance": "INTEGER",
                "salary_kind": "TEXT",
            }
            for column, column_type in migrations.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {column} {column_type}")

    def upsert_job(self, job: dict):
        values = []
        for column in JOB_COLUMNS:
            value = job.get(column)
            if column in JSON_COLUMNS:
                value = json.dumps(value or [], ensure_ascii=False)
            values.append(value)
        placeholders = ",".join("?" for _ in JOB_COLUMNS)
        updates = ",".join(f"{column}=excluded.{column}" for column in JOB_COLUMNS if column != "external_id")
        with self.connect() as db:
            db.execute(f"INSERT INTO jobs ({','.join(JOB_COLUMNS)}) VALUES ({placeholders}) ON CONFLICT(external_id) DO UPDATE SET {updates}", values)

    def upsert_jobs(self, jobs: list[dict]):
        for job in jobs:
            self.upsert_job(job)

    def _decode(self, row) -> dict:
        item = dict(row)
        for column in JSON_COLUMNS:
            item[column] = json.loads(item.get(column) or "[]")
        item["applied"] = bool(item.get("application_status"))
        return item

    def list_jobs(self, filters: dict | None = None) -> list[dict]:
        filters = filters or {}
        clauses, params = [], []

        def values_for(key):
            value = filters.get(key)
            if value is None or value == "":
                return []
            return [str(item).strip() for item in (value if isinstance(value, list) else [value]) if str(item).strip()]

        q = (filters.get("q") or "").strip()
        if q:
            clauses.append("(j.title LIKE ? OR j.organization LIKE ? OR j.work_field LIKE ? OR j.ncs LIKE ?)")
            params.extend([f"%{q}%"] * 4)

        for key, column in (("work_field", "work_field"), ("location", "location"), ("hire_type", "hire_type")):
            values = values_for(key)
            if values:
                clauses.append("(" + " OR ".join(f"j.{column} LIKE ?" for _ in values) + ")")
                params.extend(f"%{value}%" for value in values)

        for key, column in (("employment_type", "employment_type"), ("source_status", "source_status")):
            values = values_for(key)
            if values:
                clauses.append("(" + " OR ".join(f"j.{column} LIKE ?" for _ in values) + ")")
                params.extend(f"%{value}%" for value in values)

        education_patterns = {
            "무관": ["%무관%"],
            "고졸": ["%고졸%"],
            "전문학사": ["%전문학사%", "%전문대%", "%2~3년%", "%2년제%", "%3년제%"],
            "학사": ["%대졸(4년)%", "학사", "%4년제%"],
            "석사": ["%석사%"],
            "박사": ["%박사%"],
        }
        selected_education = values_for("education")
        if selected_education:
            education_parts = []
            for category in selected_education:
                patterns = education_patterns.get(category, [f"%{category}%"])
                category_parts = []
                for pattern in patterns:
                    operator = "LIKE" if "%" in pattern else "="
                    category_parts.append(f"j.education {operator} ?")
                    params.append(pattern)
                education_parts.append("(" + " OR ".join(category_parts) + ")")
            clauses.append("(" + " OR ".join(education_parts) + ")")
        if filters.get("applied") in {True, "true", "1", 1}:
            clauses.append("a.job_id IS NOT NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = f"""SELECT j.*, a.status application_status, a.notes, a.next_action_date
                    FROM jobs j LEFT JOIN applications a ON a.job_id=j.external_id
                    {where} ORDER BY CASE WHEN j.close_date='' OR j.close_date IS NULL THEN 1 ELSE 0 END, j.close_date, j.posted_date DESC"""
        with self.connect() as db:
            return [self._decode(row) for row in db.execute(query, params)]

    def get_job(self, external_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT j.*, a.status application_status, a.notes, a.next_action_date FROM jobs j LEFT JOIN applications a ON a.job_id=j.external_id WHERE j.external_id=?", (external_id,)).fetchone()
        return self._decode(row) if row else None

    def save_application(self, job_id: str, status: str, notes: str = "", next_action_date: str = ""):
        with self.connect() as db:
            db.execute("INSERT INTO applications(job_id,status,notes,next_action_date) VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,notes=excluded.notes,next_action_date=excluded.next_action_date,updated_at=CURRENT_TIMESTAMP", (job_id, status, notes, next_action_date))

    def delete_application(self, job_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM applications WHERE job_id=?", (job_id,))

    def list_applications(self) -> list[dict]:
        return self.list_jobs({"applied": True})

    def save_filter(self, name: str, criteria: dict) -> int:
        with self.connect() as db:
            cursor = db.execute("INSERT INTO saved_filters(name,criteria) VALUES(?,?)", (name, json.dumps(criteria, ensure_ascii=False)))
            return cursor.lastrowid

    def list_filters(self) -> list[dict]:
        with self.connect() as db:
            return [{"id": row["id"], "name": row["name"], "criteria": json.loads(row["criteria"])} for row in db.execute("SELECT * FROM saved_filters ORDER BY id DESC")]

    def delete_filter(self, filter_id: int):
        with self.connect() as db:
            db.execute("DELETE FROM saved_filters WHERE id=?", (filter_id,))

    def filter_options(self) -> dict:
        with self.connect() as db:
            def distinct(column):
                return [row[0] for row in db.execute(
                    f"SELECT DISTINCT {column} FROM jobs WHERE {column} IS NOT NULL AND TRIM({column}) != '' ORDER BY {column}"
                )]
            return {
                "work_field": distinct("work_field"),
                "location": distinct("location"),
                "hire_type": distinct("hire_type"),
                "education": ["무관", "고졸", "전문학사", "학사", "석사", "박사"],
            }

    def stats(self) -> dict:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            active = db.execute("SELECT COUNT(*) FROM jobs WHERE source_status='진행중'").fetchone()[0]
            applied = db.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            headcount = db.execute("SELECT COALESCE(SUM(headcount),0) FROM jobs WHERE source_status='진행중'").fetchone()[0]
        return {"total": total, "active": active, "applied": applied, "open_headcount": headcount}
