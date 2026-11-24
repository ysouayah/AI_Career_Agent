"""MassCareers (Commonwealth of Massachusetts jobs, a Taleo career section) without a browser.

The search page calls a public JSON endpoint (no login), and each job's detail page carries the full
posting in a hidden "initialHistory" field, so both are read over plain HTTP. Every job here is a
Massachusetts state job. Searches by title only; the keyword search reads the whole posting, so
cards are kept only when their own title matches (gov_sources.title_matches)."""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

from gov_sources import load_titles, title_matches, dedupe, write_results

BASE = "https://massanf.taleo.net/careersection"
PORTAL = "101430233"      # the public "ex" career section
SEARCH = f"{BASE}/rest/jobboard/searchjobs?lang=en&portal={PORTAL}"
DETAIL = f"{BASE}/ex/jobdetail.ftl?job={{}}&lang=en"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
PAUSE = 1.0               # seconds between requests
MAX_PAGES = 4             # 25 results per page


def search(keyword, page):
    body = {"multilineEnabled": False,
            "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
            "fieldData": {"fields": {"KEYWORD": keyword, "LOCATION": "", "ORGANIZATION": ""}, "valid": True},
            "filterSelectionParam": {"searchFilterSelections": [
                {"id": i, "selectedValues": []} for i in ("POSTING_DATE", "LOCATION", "JOB_FIELD", "JOB_SCHEDULE")]},
            "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []},
            "pageNo": page}
    req = urllib.request.Request(SEARCH, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA,
                                          "tz": "GMT-05:00"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _clean(field):
    s = urllib.parse.unquote(field).replace("\\:", ":").replace("!*!", " ")
    s = re.sub(r"<\s*(br|/p|/li|/div|/h\d)\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "\n- ", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


LOCATION_FIELD = re.compile(r"^(United States-|Massachusetts-|Multiple Locations)", re.I)
MONEY = re.compile(r"^\d[\d,]*\.\d\d$")
INTERVALS = ("yearly", "hourly", "weekly", "bi-weekly", "biweekly", "monthly")


def parse_detail(page):
    """{description, location, company, schedule, posted, salary}, or None when the page has no
    initialHistory. Fields come in a fixed order after the location field (job field, agency,
    schedule, shift, posted); each is stated twice, so duplicates are removed first."""
    m = re.search(r'id="initialHistory"[^>]*value="([^"]*)"', page)
    if not m:
        return None
    fields = []
    for raw in html.unescape(m.group(1)).split("!|!"):
        f = _clean(raw)
        if not fields or fields[-1] != f:
            fields.append(f)
    anchor = next((i for i, f in enumerate(fields) if LOCATION_FIELD.match(f)), None)
    if anchor is None:
        return {"description": "", "location": "", "company": "", "schedule": "", "posted": "", "salary": ""}
    long_fields = [f for f in fields[:anchor] if len(f) > 200]
    # Taleo puts the description, then the qualifications. Qualifications go first so the
    # 12k cap never cuts the requirements the hard rules read.
    long_fields = long_fields[1:] + long_fields[:1]
    nxt = lambda k: fields[anchor + k] if anchor + k < len(fields) else ""
    money = [float(f.replace(",", "")) for f in fields[anchor:anchor + 20] if MONEY.match(f)]
    interval = next((f for f in fields[anchor:anchor + 20] if f.lower() in INTERVALS), "")
    pay = (f"${min(money):,.0f}–${max(money):,.0f} {interval.lower()}".strip()
           if money and min(money) > 0 else "")
    posted = nxt(5) if re.match(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}", nxt(5)) else ""
    return {"description": "\n\n".join(long_fields)[:12000], "location": nxt(0), "company": nxt(2),
            "schedule": nxt(3), "posted": posted.split(",")[0] + ", " + posted.split(",")[1].strip()
            if posted else "", "salary": pay}


def fetch_detail(contest_no):
    req = urllib.request.Request(DETAIL.format(urllib.parse.quote(contest_no)), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def card_job_type(schedule, title):
    if re.search(r"\b(intern|internship|co-?op)\b", title, re.I):
        return "Internship"
    if re.search(r"full", schedule, re.I):
        return "Full-time"
    if re.search(r"part", schedule, re.I):
        return "Part-time"
    return ""


def run():
    started = time.time()
    titles, intern_titles = load_titles()
    searches = [(t, None) for t in titles] + [(t, "internship") for t in intern_titles]

    found, dropped, returned, errors = [], [], 0, []
    for query, track in searches:
        kept_here = 0
        for page in range(1, MAX_PAGES + 1):
            try:
                res = search(query, page)
            except Exception as e:
                errors.append(f"{query}: {e}")
                print(f"   [!] MassCareers search failed for '{query}': {e}")
                break
            reqs = res.get("requisitionList") or []
            for r in reqs:
                returned += 1
                col = r.get("column") or []
                title = (col[0] if col else "").strip()
                if not title_matches(query, title):
                    dropped.append({"query": query, "title": title})
                    continue
                try:
                    where = ", ".join(json.loads(col[1])) if len(col) > 1 else ""
                except (ValueError, TypeError):
                    where = col[1] if len(col) > 1 else ""
                job = {"query_matched": query, "title": title, "location": where,
                       "posted": col[2] if len(col) > 2 else "", "contest_no": r.get("contestNo", ""),
                       "url": DETAIL.format(r.get("contestNo", "")), "source": "MassCareers",
                       "found_by": "title_search"}
                if track:
                    job["track"] = track
                found.append(job)
                kept_here += 1
            paging = res.get("pagingData") or {}
            if page * (paging.get("pageSize") or 25) >= (paging.get("totalCount") or 0):
                break
            time.sleep(PAUSE)
        print(f"-> {query}{' (internships)' if track else ''}: {kept_here} kept")
        time.sleep(PAUSE)

    jobs = dedupe(found)
    search_s = round(time.time() - started, 1)
    no_desc, no_company = 0, 0
    for job in jobs:
        time.sleep(PAUSE)
        try:
            d = parse_detail(fetch_detail(job["contest_no"]))
        except Exception as e:
            print(f"   [!] Could not read {job['contest_no']} ({job['title']}): {e}")
            d = None
        d = d or {}
        if d.get("location"):
            job["location"] = d["location"]
        # Every MassCareers job is a Massachusetts state job; "Multiple Locations" says so too.
        if "massachusetts" not in job["location"].lower():
            job["location"] = f"{job['location']} (Massachusetts)".strip()
        job["company"] = d.get("company", "")
        job["card_job_type"] = card_job_type(d.get("schedule", ""), job["title"])
        job["salary"] = d.get("salary", "")
        job["open_date"] = d.get("posted") or job.pop("posted", "")
        job.pop("posted", None)
        job["close_date"] = ""
        job["raw_text"] = [x for x in (job["title"], job["company"], job["location"], job["salary"],
                                       f"Posted {job['open_date']}" if job["open_date"] else "") if x]
        if len(d.get("description", "")) >= 500:
            job["full_description"] = d["description"]
            job["prefilled"] = True
        else:
            no_desc += 1     # the deep scraper renders the page instead
        if not job["company"]:
            no_company += 1
            print(f"   [!] Agency not found on the detail page: {job['title']} ({job['url']})")

    elapsed = round(time.time() - started, 1)
    print(f"\nMassCareers: {returned} returned; dropped {len(dropped)} off-title; {len(jobs)} unique "
          f"job(s) kept; {len(jobs)} detail page(s) read ({no_desc} without a description, "
          f"{no_company} without an agency). Search {search_s}s, total {elapsed}s.")
    ok = not (errors and not jobs)
    write_results("masscareers", jobs, {
        "ok": ok, "message": "" if ok else f"every MassCareers search failed ({errors[0]})",
        "jobs": len(jobs), "elapsed_s": elapsed, "search_s": search_s, "detail_pages": len(jobs),
        "no_description": no_desc, "no_company": no_company, "errors": errors[:10],
        "dropped_by_title": dropped[:300]})


if __name__ == "__main__":
    try:
        run()
    except Exception as e:   # a broken source must not stop the pipeline (run_script exits on failure)
        print(f"   [!] MassCareers extractor failed: {e}")
        write_results("masscareers", [], {"ok": False, "message": f"MassCareers extractor failed: {e}", "jobs": 0})
    sys.exit(0)
