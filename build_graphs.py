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

    # Load semesters offered per course
    cur.execute("SELECT course_code, GROUP_CONCAT(DISTINCT semester) FROM sections GROUP BY course_code")
    for code, sems in cur.fetchall():
        if code in courses and sems:
            sem_list = sems.split(',')
            has_fall   = any('Fall'   in s for s in sem_list)
            has_spring = any('Spring' in s for s in sem_list)
            if has_fall and has_spring:
                courses[code]["semesters"] = "Fall & Spring 2026"
            elif has_fall:
                courses[code]["semesters"] = "Fall 2026"
            elif has_spring:
                courses[code]["semesters"] = "Spring 2026"

    return courses, prereqs, edges

def collapse_large_or(tree, known_courses, max_size=8):
    """
    Replace OR nodes with more than max_size direct course operands with an
    other_requirement. Handles cases like 'any ENGL course 1010-1990' where
    Gemini enumerates hundreds of course codes literally.
    Only counts courses that actually exist in the database.
    """
    if not tree or not isinstance(tree, dict):
        return tree
    t = tree.get("type")
    operands = tree.get("operands", [])
    if t == "OR":
        course_ops = [o for o in operands if o.get("type") == "course"]
        real_ops = [o for o in course_ops if o.get("code") in known_courses]
        if len(course_ops) > max_size:
            from collections import Counter
            depts = Counter(o.get("code", "").split()[0] for o in course_ops if o.get("code"))
            main_dept = depts.most_common(1)[0][0] if depts else "course"
            count = len(real_ops)
            desc = f"Any {main_dept} course" + (f" ({count} available)" if count > 0 else "")
            return {"type": "other_requirement", "description": desc}
        return {**tree, "operands": [collapse_large_or(o, known_courses, max_size) for o in operands]}
    if t == "AND":
        return {**tree, "operands": [collapse_large_or(o, known_courses, max_size) for o in operands]}
    return tree

def strip_self_refs(tree, code):
    """
    Recursively remove any course node matching `code` from a prereq tree.
    Used to clean self-references and cross-listed partner references.
    Unwraps single-operand AND/OR nodes; returns None if tree becomes empty.
    """
    if not tree or not isinstance(tree, dict):
        return tree
    t = tree.get("type")
    if t == "course":
        return None if tree.get("code") == code else tree
    if t in ("AND", "OR"):
        cleaned = [strip_self_refs(o, code) for o in tree.get("operands", [])]
        cleaned = [o for o in cleaned if o is not None]
        if not cleaned:
            return None
        if len(cleaned) == 1:
            return cleaned[0]
        return {**tree, "operands": cleaned}
    return tree

def get_edge_groups(tree, course_code):
    """
    Walk the prereq tree and return a dict mapping prereq_code -> group_id.
    group_id is None for required (AND) edges.
    group_id is a unique string for each OR group.
    """
    groups = {}
    counter = [0]

    def walk(node, current_group):
        t = node.get("type")
        if t == "course":
            code = node.get("code")
            if code:
                groups[code] = current_group
        elif t == "AND":
            for operand in node.get("operands", []):
                walk(operand, current_group)
        elif t == "OR":
            if current_group is not None:
                # Already inside an OR context — inherit the group
                for operand in node.get("operands", []):
                    walk(operand, current_group)
            else:
                # New top-level OR group
                gid = f"{course_code}__g{counter[0]}"
                counter[0] += 1
                for operand in node.get("operands", []):
                    walk(operand, gid)

    walk(tree, None)
    return groups

def build_graph(courses, prereqs, edges):
    G = nx.DiGraph()

    for code, meta in courses.items():
        G.add_node(code, **meta)
        if code in prereqs:
            expr = prereqs[code]["expression"]
            if expr:
                try:
                    tree = json.loads(expr) if isinstance(expr, str) else expr
                    tree = collapse_large_or(tree, courses)
                    tree = strip_self_refs(tree, code)  # remove self-references
                    expr = json.dumps(tree) if tree else None
                except Exception:
                    pass
            G.nodes[code]["prereq_expression"] = expr
            G.nodes[code]["other_requirements"] = prereqs[code]["other"]

    for course_code, prereq_code in edges:
        if course_code == prereq_code:
            continue  # skip self-loops at edge level too
        if course_code in courses and prereq_code in courses:
            group = None
            expr = G.nodes[course_code].get("prereq_expression")
            if expr:
                try:
                    tree = json.loads(expr) if isinstance(expr, str) else expr
                    group = get_edge_groups(tree, course_code).get(prereq_code)
                except Exception:
                    pass
            G.add_edge(prereq_code, course_code, group=group)

    # Remove mutual edges (cross-listed courses listing each other as prereqs)
    mutual_pairs = set()
    for u, v in list(G.edges()):
        if G.has_edge(v, u) and (v, u) not in mutual_pairs:
            mutual_pairs.add((u, v))

    if mutual_pairs:
        print(f"  Removed {len(mutual_pairs)} mutual-prereq pairs (cross-listed courses)")

    for u, v in mutual_pairs:
        G.remove_edge(u, v)
        G.remove_edge(v, u)
        # Also strip each from the other's prereq expression
        for course, other in [(u, v), (v, u)]:
            expr = G.nodes[course].get("prereq_expression")
            if expr:
                try:
                    tree = json.loads(expr) if isinstance(expr, str) else expr
                    tree = strip_self_refs(tree, other)
                    G.nodes[course]["prereq_expression"] = json.dumps(tree) if tree else None
                except Exception:
                    pass

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
            "semesters":    data.get("semesters"),
            "external":     code in external_prereqs,
        })

    edges = []
    for src, tgt, data in G.edges(data=True):
        if src in all_nodes and tgt in all_nodes:
            edges.append({"source": src, "target": tgt, "group": data.get("group")})

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

    # Check for remaining cycles
    cycles = list(nx.simple_cycles(G))
    if cycles:
        print(f"  Warning: {len(cycles)} cycles remaining (likely data issues)")

    departments = sorted({d["department"] for d in courses.values() if d["department"]})
    print(f"\nExporting {len(departments)} department graphs to {OUT_DIR}/...")

    for dept in departments:
        result = export_department(G, dept, OUT_DIR)
        if result:
            nodes, edges_count = result
            print(f"  {dept}: {nodes} nodes, {edges_count} edges")

    # Export catalog.json: {code: title} for all courses
    catalog = {code: meta["title"] for code, meta in courses.items()}
    catalog_path = os.path.join(OUT_DIR, "catalog.json")
    with open(catalog_path, "w") as f:
        json.dump(catalog, f)
    print(f"\nExported catalog with {len(catalog)} courses to {catalog_path}")

    # Export credits.json: {code: credits} — integer credits only, skip variable-credit courses
    credits = {}
    for code, meta in courses.items():
        ch = meta.get("credit_hours", "")
        try:
            val = int(str(ch).split()[0])
            if val > 0:
                credits[code] = val
        except (ValueError, IndexError):
            pass
    credits_path = os.path.join(OUT_DIR, "credits.json")
    with open(credits_path, "w") as f:
        json.dump(credits, f)
    print(f"Exported credits for {len(credits)} courses to {credits_path}")

    conn.close()
    print(f"Done. Graphs saved to {OUT_DIR}/")

if __name__ == "__main__":
    main()
