import requests
import json
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://soc.uvm.edu/api/?page=fose&route={}"

SEMESTERS = {
    "Fall 2026":   "202609",
    "Spring 2026": "202601",
}

def get_all_sections(srcdb):
    resp = requests.post(
        API.format("search"),
        json={"other": {"srcdb": srcdb}, "criteria": []}
    )
    resp.raise_for_status()
    return resp.json()["results"]

def get_section_detail(crn, srcdb):
    resp = requests.post(
        API.format("details"),
        json={"key": f"crn:{crn}", "srcdb": srcdb}
    )
    resp.raise_for_status()
    return resp.json()

def parse_detail(data, semester_label):
    course = {"semester": semester_label}

    if data.get("code"):
        course["course_code"] = data["code"]
        course["department"] = data["code"].split()[0]
    if data.get("section") and data.get("crn"):
        course["section"] = f"Section {data['section']}, CRN {data['crn']}"
    if data.get("title"):
        course["title"] = data["title"]
    if data.get("hours_html"):
        course["credit_hours"] = data["hours_html"]

    if data.get("meeting_html"):
        soup = BeautifulSoup(data["meeting_html"], "html.parser")
        course["meeting_info"] = soup.get_text(strip=True)

    if data.get("instructordetail_html"):
        soup = BeautifulSoup(data["instructordetail_html"], "html.parser")
        div = soup.find("div", class_="instructor-detail")
        if div:
            course["instructor"] = div.get_text(strip=True)

    if data.get("description"):
        course["description"] = data["description"]

    if data.get("expanded_sect_details"):
        soup = BeautifulSoup(data["expanded_sect_details"], "html.parser")
        for div in soup.find_all("div", class_="text"):
            text = div.get_text(strip=True)
            if text.startswith("Section Description:"):
                course["section_description"] = text.replace("Section Description:", "").strip()
            elif text.startswith("Section Expectations:"):
                course["section_expectations"] = text.replace("Section Expectations:", "").strip()
            elif text.startswith("Evaluation:"):
                course["evaluation"] = text.replace("Evaluation:", "").strip()

    if data.get("clssnotes"):
        soup = BeautifulSoup(data["clssnotes"], "html.parser")
        course["soc_comments"] = soup.get_text(strip=True)

    return course

def scrape_semester(semester_label, srcdb):
    print(f"\nScraping {semester_label}...")
    sections = get_all_sections(srcdb)
    print(f"Found {len(sections)} sections across all departments")

    results = []
    completed = 0

    def fetch(section):
        detail = get_section_detail(section["crn"], srcdb)
        return parse_detail(detail, semester_label)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch, s): s for s in sections}
        for future in as_completed(futures):
            completed += 1
            if completed % 100 == 0:
                print(f"  {completed}/{len(sections)}")
            try:
                results.append(future.result())
            except Exception as e:
                s = futures[future]
                print(f"  ERROR {s['code']} CRN {s['crn']}: {e}")

    results.sort(key=lambda x: (x.get("department", ""), x.get("course_code", ""), x.get("section", "")))

    filename = f"all_courses_{semester_label.lower().replace(' ', '_')}.json"
    with open(filename, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {len(results)} sections to {filename}")
    return results

if __name__ == "__main__":
    for label, srcdb in SEMESTERS.items():
        scrape_semester(label, srcdb)
