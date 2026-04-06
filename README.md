# UVM Prerequisite Graphs

An interactive visualization of course prerequisites for every department at the University of Vermont. Built because the information exists but has never been easy to see all at once.

## What it does

- Browse prerequisite graphs for any UVM department
- Hover a course to see its prerequisites, credits, and when it's offered
- Click once for direct neighbors, twice for the full prereq chain, three times to see what a course unlocks
- Track your completed courses with My Courses mode. The graph colors what's locked, available, and done
- Import your UVM degree audit and AI will check off your completed courses automatically
- Search for any course by name or code

## Tech

- [D3.js](https://d3js.org) for the force-directed graph
- [dagre](https://github.com/dagrejs/dagre) for the hierarchical layout
- Python + SQLite for scraping and building the course database
- Gemini (via Cloudflare Workers) for parsing degree audits and extracting prerequisites from course descriptions
- Hosted on GitHub Pages

## Running locally

Just open `index.html` in a browser. No build step needed.

## Rebuilding the graphs

If you have a `courses.db` database populated with UVM course data:

```bash
pip install networkx
python build_graphs.py
```

This regenerates everything in `graphs/`.
