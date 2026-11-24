"""§0.2 search probe (work session): per file, forms (a) (b) (c) until HTTP 200 with total_count > 0.
Writes probe/search_<F>_<form>.json (raw first page + headers) and probe/search.json (summary)."""
import datetime as dt
import json
from pathlib import Path

import ghapi

HERE = Path(__file__).resolve().parent
FORMS = {"a": "filename:{F} path:/", "b": "filename:{F}", "c": "{STEM} filename:{F}"}


def main():
    c = ghapi.Client(use_gh=True, code_per_min=4)
    summary = {}
    for F, stem in (("AGENTS.md", "AGENTS"), ("CLAUDE.md", "CLAUDE")):
        summary[F] = {"tried": [], "form": None}
        for form, tmpl in FORMS.items():
            query = tmpl.format(F=F, STEM=stem)
            st, data, hd = c.get(f"search/code?q={ghapi.q(query)}&per_page=100", "code")
            items = (data or {}).get("items") or [] if isinstance(data, dict) else []
            kept = [i for i in items if i.get("path") == F]
            rec = {"form": form, "query": query, "status": st,
                   "total_count": data.get("total_count") if isinstance(data, dict) else None,
                   "incomplete_results": data.get("incomplete_results") if isinstance(data, dict) else None,
                   "items_page1": len(items), "kept_path_eq_F_page1": len(kept),
                   "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "ratelimit": {k: v for k, v in hd.items() if k.lower().startswith("x-ratelimit")}}
            (HERE / "probe" / f"search_{F}_{form}.json").write_text(
                json.dumps({"record": rec, "response": data}, indent=1, sort_keys=True))
            summary[F]["tried"].append(rec)
            print(json.dumps(rec))
            if st == 200 and (rec["total_count"] or 0) > 0:
                summary[F]["form"] = form
                break
    (HERE / "probe" / "search.json").write_text(json.dumps(summary, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
