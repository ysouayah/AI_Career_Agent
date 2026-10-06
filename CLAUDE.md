# AI Career Agent

Autonomous job-search pipeline for Youssef Souayah (BU, Data Science + Political Science, graduating
May 2027). Runs every Monday on GitHub Actions, scrapes job boards, grades postings against his
resume, and emails a report plus tailored application packages.

## Pipeline (run_everything.py orchestrates; each phase is a separate script)
1. `brainstormer.py` → `search_targets.json` (search titles; first location is always Boston)
2. Extractors → `*_jobs.json`: `linkedin_extractor.py`, `indeed_extractor.py` (board-side entry-level +
   full-time filters), `handshake_extractor.py` (needs `handshake_state.json`; see Handshake below)
3. Card stage in run_everything: normalize cards (Handshake has its own layout), location check,
   card job-type check, relevance ranking, cap to the top 80 for the sifter
4. `deep_scraper.py` → full descriptions (`deep_jobs.json`); failures are kept with an empty
   description so they're retried, never silently dropped
5. Extraction + hard rules (`apply_rules`), grading, caps, duplicate check, closed-posting check
6. Report (`FINAL_STRATEGY.md`, emailed) and packages via `auto_fulfiller.py`
7. Run log: `agent_log.csv` + `postings.jsonl`; `update_tracker.py` imports into the local tracker

Config lives in `user_config.json` (candidate facts, hard vetos, report settings). Code changes the
rules fingerprint, which re-evaluates previously rejected jobs on the next run.

## Design rules (each came from a real failure; don't undo them)
- **Hard rules fire only on evidence.** Every disqualifier needs a quote that appears verbatim in the
  posting (`quote_found`). No quote, or a quote that doesn't support the claim, means the rule
  doesn't fire. Example: "immediate hire" needs a quote about start timing, not "recent grads welcome".
- **Soft problems cap, they don't hide.** Caps keep jobs visible as near misses with the reason in
  the text: unmet required skill / title tech / preferred 1+ yrs / off-target core work → 79;
  start before availability → 84; open-now role while availability is >4 months away → 84.
- **Coursework doesn't satisfy hard requirements.** Resume lines marked "(coursework)" are ignored by
  the required-skill checks (`experience_text`).
- **Fail visibly.** Expired Handshake session, zero Handshake jobs, unverifiable links: say so in the
  log and the report. A silent empty result is a bug.
- **Duplicates must agree on title.** Near-identical text with different titles is a different role
  (Veeva shares boilerplate across tracks); different titles need ≥97% identical text.
- **Closed postings:** check the employer's own link. Handshake keeps listings open after the
  employer closes them, so Handshake jobs are checked at `external_url` when one was found.

## Resume and letter generation (auto_fulfiller.py)
- `master_resume.md` is the single source of truth. Never add a fact, number, tool or claim that
  isn't in it. `ground_resume()` strips unsourced filler, restores dropped metrics, flags new numbers.
- Entries stay in reverse-chronological order; output must be one page.
- Cover letters open "Dear Hiring Team", state availability once, never self-grade.

## Handshake
- Session: `handshake_auth.py` (manual BU login + Duo) writes `handshake_state.json` and
  `handshake_state.b64`; the .b64 goes in the GitHub secret `HANDSHAKE_STATE`. Sessions expire.
- Playwright sync API: never wait with `time.sleep` — use `page.wait_for_timeout`, or URLs and tabs
  stop updating.
- The "refer a friend" banner covers pagination; remove it and click via JS (`go_to_next_page`).

## Files you must never commit or hand-edit
- Never commit: `handshake_state.json`, `handshake_state.b64`, `secrets.toml`, `.streamlit/`,
  `credentials.json`, `agent_tracker.xlsx` (local only), anything in `.gitignore`.
- Bot-owned, updated by the Monday workflow: `memory_bank.db`, `agent_log.csv`, `postings.jsonl`.
  Don't edit them by hand.

## Git workflow
- The GitHub bot commits after every run, so always start with `git pull --rebase --autostash`.
- Push with `git ship` (alias: pull --rebase --autostash, then push).
- At the end of any change, give Youssef the exact commands: `git add <files>`, `git commit -m "..."`,
  `git ship`. Name the files explicitly.
- Workflow file: `.github/workflows/weekly_agent.yml` (runner pinned to ubuntu-24.04, schedule in
  America/New_York).

## How to make a change
1. Reproduce the failure first with the real case (the actual posting text, quote, or log line).
2. Fix it, then show before/after on that case, plus a case that must NOT change.
3. `python -m py_compile` every changed file; run the relevant scripts locally when possible.
4. Tell Youssef which test case to add to the tracker's "Test cases" tab (ID, company, what failed,
   expected behavior, fix, status).
5. Use Plan mode for anything touching more than one phase of the pipeline.

## Working with Youssef
- Plain explanations; say what was verified and what wasn't.
- Never invent facts about his experience. If a tailored claim isn't in the master resume, ask.
- He is Boston-based and can't relocate; availability is preferably September 2027, open to
  earlier starts for the right role (those show as near misses, not approvals).