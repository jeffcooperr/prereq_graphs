import sqlite3
import json

DB = "courses.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    semester        TEXT,
    department      TEXT,
    course_code     TEXT,
    crn             TEXT,
    section         TEXT,
    title           TEXT,
    credit_hours    TEXT,
    meeting_info    TEXT,
    instructor      TEXT,
    description     TEXT,
    section_description  TEXT,
    section_expectations TEXT,
    evaluation      TEXT,
    soc_comments    TEXT
);

CREATE TABLE IF NOT EXISTS prerequisites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code     TEXT NOT NULL,
    prereq_code     TEXT NOT NULL,
    raw_text        TEXT,
    UNIQUE(course_code, prereq_code)
);

CREATE INDEX IF NOT EXISTS idx_sections_course_code ON sections(course_code);
CREATE INDEX IF NOT EXISTS idx_sections_department  ON sections(department);
CREATE INDEX IF NOT EXISTS idx_sections_semester    ON sections(semester);
CREATE INDEX IF NOT EXISTS idx_prereqs_course_code  ON prerequisites(course_code);
"""

FILES = [
    "all_courses_fall_2026.json",
    "all_courses_spring_2026.json",
]

def load(conn, path):
    with open(path) as f:
        rows = json.load(f)

    cur = conn.cursor()
    inserted = 0
    for r in rows:
        cur.execute("""
            INSERT INTO sections
                (semester, department, course_code, crn, section, title, credit_hours,
                 meeting_info, instructor, description, section_description,
                 section_expectations, evaluation, soc_comments)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r.get("semester"),
            r.get("department"),
            r.get("course_code"),
            r.get("section", "").split("CRN ")[-1] if "CRN" in r.get("section", "") else None,
            r.get("section"),
            r.get("title"),
            r.get("credit_hours"),
            r.get("meeting_info"),
            r.get("instructor"),
            r.get("description"),
            r.get("section_description"),
            r.get("section_expectations"),
            r.get("evaluation"),
            r.get("soc_comments"),
        ))
        inserted += 1

    conn.commit()
    print(f"  Loaded {inserted} sections from {path}")

if __name__ == "__main__":
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)

    for f in FILES:
        load(conn, f)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sections")
    print(f"\nTotal sections in DB: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(DISTINCT department) FROM sections")
    print(f"Departments: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(DISTINCT course_code) FROM sections")
    print(f"Unique courses: {cur.fetchone()[0]}")

    conn.close()
    print(f"\nDatabase ready: {DB}")
