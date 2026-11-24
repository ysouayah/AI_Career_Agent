"""USAJobs (federal jobs) through the official Search API: https://data.usajobs.gov/api/search.

Searches every title in search_targets.json around Boston. Remote postings come back in the same
results; one is kept only if it doesn't pay relocation (a relocation package means moving). The API
returns the full posting, so these jobs carry their description and skip the deep scrape.
Needs USAJOBS_API_KEY and USAJOBS_EMAIL; without them the source is skipped, never crashed."""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from gov_sources import load_secrets, load_titles, title_matches, dedupe, write_results

API = "https://data.usajobs.gov/api/search"
LOCATION = "Boston, Massachusetts"
RADIUS = 25          # miles
PER_PAGE = 100
MAX_PAGES = 3        # per title
# HiringPath values a member of the public can apply under. Anything else (current federal
# employees, veterans' and spouses' programs) is closed to the candidate.
OPEN_PATHS = {"public", "graduates", "student"}
MA_LOC = re.compile(r"massachusetts|,\s*ma\b", re.I)
# The search API returns these with empty names, so the codes are mapped here (from
# https://data.usajobs.gov/api/codelist/positionscheduletypes and .../positionofferingtypes).
SCHEDULES = {"1": "Full-time", "2": "Part-time", "3": "Shift work", "4": "Intermittent",
             "5": "Job sharing", "6": "Multiple schedules"}
OFFERINGS = {"15317": "Permanent", "15318": "Temporary", "15319": "Term", "15320": "Detail",
             "15321": "Temporary promotion", "15322": "Seasonal", "15323": "Summer",
             "15326": "Recent graduates", "15327": "Multiple", "15328": "Internships",
             "15522": "Intermittent", "15667": "ICTAP only", "15668": "Agency employees only"}


def _named(items, codes):
    return ", ".join(i.get("Name") or codes.get(str(i.get("Code")), "") for i in items or [])


def fetch(params, headers):
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)["SearchResult"]


def as_text(value):
    if isinstance(value, list):
        return "\n".join(f"- {v}" for v in value if str(v).strip())
    return str(value or "").strip()


def description(d, ud):
    """Qualifications first: the deep scraper caps at 12k characters and so does this."""
    parts = [("Summary", ud.get("JobSummary")),
             ("Qualifications", d.get("QualificationSummary")),
             ("Education", ud.get("Education")),
             ("Key requirements", ud.get("KeyRequirements")),
             ("Requirements", ud.get("Requirements")),
             ("Major duties", ud.get("MajorDuties")),
             ("How you will be evaluated", ud.get("Evaluations")),
             ("Other information", ud.get("OtherInformation")),
             ("Who may apply", ", ".join(ud.get("HiringPathDisplay") or []))]
    head = (f"{d.get('PositionTitle', '')}\n{d.get('OrganizationName', '')}, {d.get('DepartmentName', '')}\n"
            f"Location: {d.get('PositionLocationDisplay', '')}\n")
    body = "\n\n".join(f"{label}:\n{as_text(v)}" for label, v in parts if as_text(v))
    return (head + "\n" + body)[:12000]


def salary(d):
    pay = (d.get("PositionRemuneration") or [{}])[0]
    lo, hi = pay.get("MinimumRange"), pay.get("MaximumRange")
    try:
        span = f"${float(lo):,.0f}–${float(hi):,.0f}"
    except (TypeError, ValueError):
        return ""
    return f"{span} {(pay.get('Description') or '').lower()}".strip()


def job_type(d, title):
    """Card job type in the form card_type_ok reads. "Internship" sends the card to the internship
    pool, the same as a Handshake internship card. An unusual schedule is left blank for extraction."""
    offering = _named(d.get("PositionOfferingType"), OFFERINGS)
    if re.search(r"\bintern|student trainee", title, re.I):
        return "Internship"
    # Only the title makes a card an internship. The Air Force's new-graduate career programs
    # ("Data Scientist", "Operations Research Analyst") carry the "Internships" offering code; as
    # internship cards they'd be judged for a spring term they don't have. Extraction reads them.
    offering = offering.replace("Internships", "intern program")
    schedule = _named(d.get("PositionSchedule"), SCHEDULES)
    if re.search(r"full", schedule, re.I):
        return f"Full-time · {offering}".strip(" ·")
    if re.search(r"part", schedule, re.I):
        return f"Part-time · {offering}".strip(" ·")
    return ""


def card_location(d):
    """The Massachusetts locations, not "Multiple Locations": the card-stage location check reads
    this line, and a nationwide announcement with a Boston slot must pass it."""
    places = [l.get("LocationName", "") for l in d.get("PositionLocation") or []]
    ma = [p for p in places if MA_LOC.search(p)]
    if not ma:
        return d.get("PositionLocationDisplay", "").strip()
    others = len(places) - len(ma)
    return "; ".join(ma) + (f" (+{others} other location{'s' if others > 1 else ''})" if others else "")


def to_card(d, query, track):
    ud = (d.get("UserArea") or {}).get("Details") or {}
    title = d.get("PositionTitle", "").strip()
    org = d.get("OrganizationName", "").strip()
    location = card_location(d)
    pay = salary(d)
    opened, closes = (d.get("PublicationStartDate") or "")[:10], (d.get("ApplicationCloseDate") or "")[:10]
    card = {
        "query_matched": query,
        "title": title,
        "company": org,
        "location": location,
        "url": d.get("PositionURI", "").replace(":443", ""),
        "source": "USAJobs",
        "found_by": "title_search",
        "card_job_type": job_type(d, title),
        "salary": pay,
        "open_date": opened,
        "close_date": closes,
        "raw_text": [x for x in (title, org, d.get("DepartmentName", ""), location, pay,
                                 f"Open {opened} – closes {closes}") if x],
        "full_description": description(d, ud),
        "prefilled": True,
    }
    if track:
        card["track"] = track
    return card


def where_ok(d):
    """In Massachusetts, or remote without a relocation package."""
    ud = (d.get("UserArea") or {}).get("Details") or {}
    if any(MA_LOC.search(l.get("LocationName", "")) for l in d.get("PositionLocation") or []):
        return True
    return bool(ud.get("RemoteIndicator")) and str(ud.get("Relocation")).lower() != "true"


def run():
    started = time.time()
    load_secrets()
    key, email = os.environ.get("USAJOBS_API_KEY", "").strip(), os.environ.get("USAJOBS_EMAIL", "").strip()
    if not key or not email:
        msg = "USAJOBS_API_KEY or USAJOBS_EMAIL is not set; USAJobs skipped"
        print(f"   [!] {msg}.")
        write_results("usajobs", [], {"ok": False, "message": msg, "jobs": 0})
        return
    headers = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
    titles, intern_titles = load_titles()
    searches = [(t, None) for t in titles] + [(t, "internship") for t in intern_titles]

    jobs, dropped, counts, errors = [], [], {"returned": 0, "title": 0, "where": 0, "path": 0}, []
    for query, track in searches:
        kept_here = 0
        for page in range(1, MAX_PAGES + 1):
            try:
                res = fetch({"PositionTitle": query, "LocationName": LOCATION, "Radius": RADIUS,
                             "ResultsPerPage": PER_PAGE, "Page": page}, headers)
            except Exception as e:
                errors.append(f"{query}: {e}")
                print(f"   [!] USAJobs search failed for '{query}': {e}")
                break
            items = res.get("SearchResultItems") or []
            for item in items:
                d = item.get("MatchedObjectDescriptor") or {}
                counts["returned"] += 1
                ud = (d.get("UserArea") or {}).get("Details") or {}
                if not title_matches(query, d.get("PositionTitle")):
                    counts["title"] += 1
                    dropped.append({"query": query, "title": d.get("PositionTitle")})
                    continue
                if not where_ok(d):
                    counts["where"] += 1
                    continue
                if not OPEN_PATHS & set(ud.get("HiringPath") or []):
                    counts["path"] += 1
                    continue
                jobs.append(to_card(d, query, track))
                kept_here += 1
            if page * PER_PAGE >= int(res.get("SearchResultCountAll") or 0):
                break
            time.sleep(0.5)
        print(f"-> {query}{' (internships)' if track else ''}: {kept_here} kept")
        time.sleep(0.5)

    jobs = dedupe(jobs)
    elapsed = round(time.time() - started, 1)
    print(f"\nUSAJobs: {counts['returned']} returned; dropped {counts['title']} off-title, "
          f"{counts['where']} outside MA (or remote with relocation), {counts['path']} closed to the "
          f"public; {len(jobs)} unique job(s) kept in {elapsed}s.")
    ok = not (errors and not jobs)
    write_results("usajobs", jobs, {
        "ok": ok, "message": "" if ok else f"every USAJobs search failed ({errors[0]})",
        "jobs": len(jobs), "elapsed_s": elapsed, "counts": counts, "errors": errors[:10],
        "dropped_by_title": dropped[:300]})


if __name__ == "__main__":
    try:
        run()
    except Exception as e:   # a broken source must not stop the pipeline (run_script exits on failure)
        print(f"   [!] USAJobs extractor failed: {e}")
        write_results("usajobs", [], {"ok": False, "message": f"USAJobs extractor failed: {e}", "jobs": 0})
    sys.exit(0)
