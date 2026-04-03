import sqlite3
import json
import os
import networkx as nx

DB = "courses.db"
OUT_DIR = "graphs"

def load_data(conn):
    cur = conn.cursor()

    # Load all unique courses with metadata
    cur.execute("""
        SELECT DISTINCT s.course_code, s.department, s.title, s.credit_hours, s.description
        FROM sections s
        GROUP BY s.course_code
        HAVING LENGTH(s.title) = MAX(LENGTH(s.title))
    """)
    courses = {row[0]: {
        "course_code": row[0],
        "department":  row[1],
        "title":       row[2],
        "credit_hours": row[3],
        "description": row[4],
    } for row in cur.fetchall()}

    # Load prereq expressions
    cur.execute("SELECT course_code, prereq_expression, other_requirements FROM course_prereqs")
    prereqs = {row[0]: {"expression": row[1], "other": row[2]} for row in cur.fetchall()}

    # Load flat edges
    cur.execute("SELECT course_code, prereq_code FROM prerequisites")
    edges = cur.fetchall()

    return courses, prereqs, edges

def build_graph(courses, prereqs, edges):
    G = nx.DiGraph()

    for code, meta in courses.items():
        G.add_node(code, **meta)
        if code in prereqs:
            G.nodes[code]["prereq_expression"] = prereqs[code]["expression"]
            G.nodes[code]["other_requirements"] = prereqs[code]["other"]

    for course_code, prereq_code in edges:
        # Only add edge if both nodes exist in our course list
        if course_code in courses and prereq_code in courses:
            G.add_edge(prereq_code, course_code)  # prereq → course

    return G

def export_department(G, department, out_dir):
    # Get all nodes for this department + any prereqs from other departments
    dept_courses = {n for n, d in G.nodes(data=True) if d.get("department") == department}
    if not dept_courses:
        return 0

    # Include cross-department prereqs that feed into this department
    external_prereqs = set()
    for node in dept_courses:
        for prereq in G.predecessors(node):
            if prereq not in dept_courses:
                external_prereqs.add(prereq)

    all_nodes = dept_courses | external_prereqs

    nodes = []
    for code in all_nodes:
        data = G.nodes[code]
        nodes.append({
            "id":           code,
            "course_code":  code,
            "department":   data.get("department", ""),
            "title":        data.get("title", ""),
            "credit_hours": data.get("credit_hours", ""),
            "description":  data.get("description", ""),
            "prereq_expression":  data.get("prereq_expression"),
            "other_requirements": data.get("other_requirements"),
            "external":     code in external_prereqs,
        })

    edges = []
    for src, tgt in G.edges():
        if src in all_nodes and tgt in all_nodes:
            edges.append({"source": src, "target": tgt})

    out = {"department": department, "nodes": nodes, "edges": edges}
    path = os.path.join(out_dir, f"{department}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    return len(nodes), len(edges)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB)

    print("Loading data...")
    courses, prereqs, edges = load_data(conn)
    print(f"  {len(courses)} courses, {len(edges)} edges")

    print("Building graph...")
    G = build_graph(courses, prereqs, edges)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Check for cycles
    cycles = list(nx.simple_cycles(G))
    if cycles:
        print(f"  Warning: {len(cycles)} cycles found (likely data issues)")

    departments = sorted({d["department"] for d in courses.values() if d["department"]})
    print(f"\nExporting {len(departments)} department graphs to {OUT_DIR}/...")

    for dept in departments:
        result = export_department(G, dept, OUT_DIR)
        if result:
            nodes, edges_count = result
            print(f"  {dept}: {nodes} nodes, {edges_count} edges")

    conn.close()
    print(f"\nDone. Graphs saved to {OUT_DIR}/")

if __name__ == "__main__":
    main()
