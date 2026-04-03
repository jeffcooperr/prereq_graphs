import sqlite3
import json
import time
import re
from google import genai
import os
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = "courses.db"
MODEL = "gemini-2.5-flash-lite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_prereqs (
    course_code         TEXT PRIMARY KEY,
    prereq_expression   TEXT,
    other_requirements  TEXT,
    raw_description     TEXT,
    extracted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

SYSTEM = """You extract prerequisite information from university course descriptions.

Return JSON with this structure:
{
  "has_prerequisites": true or false,
  "prereqs": null or a tree node,
  "other_requirements": null or a plain text string for anything that isn't a course code
}

Tree nodes:
- Course:  { "type": "course", "code": "DEPT 1234" }
- AND:     { "type": "AND", "operands": [ ...nodes ] }
- OR:      { "type": "OR",  "operands": [ ...nodes ] }

Rules:
- Only extract actual course codes (e.g. CS 1210, MATH 2248)
- "and" between courses → AND node
- "or" between courses → OR node
- A comma-separated list of courses where only the LAST item has "or" before it means the entire list is OR (e.g. "A, B, C, or D" → OR of A, B, C, D)
- Semicolons separate independent requirements that must ALL be met → AND
- Instructor permission, class standing, GPA, etc. → other_requirements string
- If no prerequisites at all → has_prerequisites: false, prereqs: null
- Return only valid JSON, no explanation"""

def strip_html(text):
    if not text:
        return ""
    if "<" in text and ">" in text:
        return BeautifulSoup(text, "html.parser").get_text(separator=" ").strip()
    return text.strip()

def extract(client, course_code, description):
    prompt = f"{SYSTEM}\n\nCourse: {course_code}\nDescription: {description}"
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    raw = resp.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)

def main():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)

    # Get one description per unique course (prefer longer descriptions)
    cur = conn.cursor()
    cur.execute("""
        SELECT course_code, description, soc_comments, section_description, section_expectations
        FROM sections
        WHERE description IS NOT NULL AND description != ''
        GROUP BY course_code
        HAVING LENGTH(description) = MAX(LENGTH(description))
    """)
    courses = cur.fetchall()
    print(f"Extracting prerequisites for {len(courses)} unique courses...")

    # Skip already processed
    cur.execute("SELECT course_code FROM course_prereqs")
    done = {r[0] for r in cur.fetchall()}
    courses = [(c, d, s, sd, se) for c, d, s, sd, se in courses if c not in done]
    print(f"{len(courses)} remaining after skipping already processed")

    # Skip courses with no prereq-related text in any field
    PREREQ_TERMS = ["prerequisite", "prereq", "pre-req", "pre req", "coreq", "co-req", "permission", "concurrent", "standing"]
    def has_prereq_text(row):
        _, description, soc_comments, section_description, section_expectations = row
        combined = " ".join(f.lower() for f in [description, soc_comments, section_description, section_expectations] if f)
        return any(term in combined for term in PREREQ_TERMS)

    courses = [r for r in courses if has_prereq_text(r)]
    print(f"{len(courses)} remaining after skipping courses with no prereq text")

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    completed = 0
    errors = 0

    def process(row):
        course_code, description, soc_comments, section_description, section_expectations = row
        parts = [strip_html(f) for f in [description, soc_comments, section_description, section_expectations] if f]
        text = " ".join(parts)
        print(f"  Fetching {course_code}...", flush=True)
        result = extract(client, course_code, text)
        return course_code, text, result

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process, row): row for row in courses}
        for future in as_completed(futures):
            completed += 1
            print(f"  {completed}/{len(courses)}", end="\r", flush=True)
            try:
                course_code, text, result = future.result()
                conn.execute("""
                    INSERT OR REPLACE INTO course_prereqs
                        (course_code, prereq_expression, other_requirements, raw_description)
                    VALUES (?, ?, ?, ?)
                """, (
                    course_code,
                    json.dumps(result.get("prereqs")) if result.get("prereqs") else None,
                    result.get("other_requirements"),
                    text,
                ))
                conn.commit()
            except Exception as e:
                errors += 1
                print(f"  ERROR {futures[future][0]}: {e}")

    cur.execute("SELECT COUNT(*) FROM course_prereqs WHERE prereq_expression IS NOT NULL")
    with_prereqs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM course_prereqs")
    total = cur.fetchone()[0]

    print(f"\nDone. {total} courses processed, {with_prereqs} have prerequisites, {errors} errors.")
    conn.close()

if __name__ == "__main__":
    main()
