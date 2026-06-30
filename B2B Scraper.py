"""
B2B Job-Signal Lead Scraper
Collects full company + job details from multiple portals.

Sources:
  1. Adzuna API   -- free, US + UK, returns company/salary/description
  2. LinkedIn     -- HTML scrape (public, no login)
  3. Reed.co.uk   -- UK jobs (optional, set REED_API_KEY env var)

CSV fields:
  job_title | company | company_domain | location | job_url |
  posted_date | salary | job_type | description | source_portal | scraped_at

Usage:
  pip install -r requirements.txt
  python scraper.py              # full run -> leads.csv + push to Sheets
  python scraper.py --test       # 3 roles, API only -> test_leads.csv
  python scraper.py --sheets-only  # push existing CSV to Sheets only
  python scraper.py --source adzuna|linkedin|reed
"""

import argparse
import csv
import hashlib
import logging
import os
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, fields as dc_fields
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSHEETS_AVAILABLE = True
except ImportError:
    GSHEETS_AVAILABLE = False


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

OUTPUT_CSV    = "leads.csv"
REQUEST_DELAY = (2, 5)
MAX_PER_QUERY = 25
DETAIL_FETCH  = True

# Google Sheets -- set these via environment variables, see README.md
SHEET_ID    = os.environ.get("GSHEET_ID", "")
SHEET_TAB   = os.environ.get("GSHEET_TAB", "Leads")
CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")

# Adzuna API (free -- developer.adzuna.com) -- set via environment variables
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRIES = ["us", "gb"]

LOCATIONS_US_UK = ["United States", "United Kingdom", "Remote"]

TARGET_ROLES = [
    "Chief Revenue Officer", "VP Revenue", "Head of Revenue",
    "Revenue Operations", "Director Revenue Operations",
    "VP Sales", "Head of Sales", "Sales Director",
    "Sales Operations Manager", "Sales Enablement",
    "CMO", "VP Marketing", "Head of Marketing",
    "Growth Manager", "Demand Generation Manager",
    "Marketing Operations Manager",
    "Head of Growth", "GTM Engineer", "GTM Operations",
    "Business Development Manager",
    "Founder", "Co-Founder", "CEO", "Managing Director",
    "Head of Operations", "COO",
    "CRM Manager", "HubSpot Administrator", "Salesforce Administrator",
    "Revenue Systems Manager",
    "Head of AI", "AI Lead", "Solutions Architect",
    "SDR Manager", "BDR Manager", "Head of Business Development",
]

PRIORITY_ROLES = [
    "VP Sales", "Head of Sales", "VP Marketing", "CMO",
    "Head of Growth", "Revenue Operations", "GTM Engineer",
    "Head of Revenue", "CEO", "Head of AI",
    "SDR Manager", "BDR Manager", "CRO", "COO",
    "HubSpot Administrator", "Salesforce Administrator",
]

@dataclass
class JobLead:
    job_title:      str = ""
    company:        str = ""      # <- company name (the actual lead)
    company_domain: str = ""      # <- company website domain
    location:       str = ""
    job_url:        str = ""
    posted_date:    str = ""
    salary:         str = ""
    job_type:       str = ""
    description:    str = ""
    source_portal:  str = ""
    scraped_at:     str = ""

    def __post_init__(self):
        if not self.scraped_at:
            self.scraped_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        if self.description and len(self.description) > 600:
            self.description = self.description[:597] + "..."

    def uid(self):
        key = self.job_url.strip().lower().split("?")[0]
        return hashlib.md5(key.encode()).hexdigest()

    def is_valid(self):
        return bool(self.job_title and self.company and self.job_url)


CSV_FIELDS = [f.name for f in dc_fields(JobLead)]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

SESSION = requests.Session()

def get_headers(extra=None):
    h = {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "DNT":             "1",
    }
    if extra:
        h.update(extra)
    return h

def polite_sleep(lo=2, hi=5):
    time.sleep(random.uniform(lo, hi))

def fetch_html(url, timeout=15, retries=3):
    for attempt in range(retries):
        try:
            polite_sleep()
            r = SESSION.get(url, headers=get_headers(), timeout=timeout)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "lxml")
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                log.warning("Rate limited. Sleeping %ds...", wait)
                time.sleep(wait)
            elif r.status_code in (401, 403):
                log.debug("Blocked %d: %s", r.status_code, url)
                return None
            else:
                log.debug("HTTP %d: %s", r.status_code, url)
        except requests.RequestException as e:
            log.debug("Request error attempt %d: %s", attempt + 1, e)
            time.sleep(4 * (attempt + 1))
    return None

def fetch_json(url, extra_headers=None, timeout=15):
    try:
        polite_sleep(1, 3)
        h = get_headers({"Accept": "application/json, */*"})
        if extra_headers:
            h.update(extra_headers)
        r = SESSION.get(url, headers=h, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.debug("JSON %d: %s", r.status_code, url)
    except Exception as e:
        log.debug("JSON fetch error: %s", e)
    return None

def clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip()

def strip_html_to_text(html, max_chars=600):
    text = BeautifulSoup(html or "", "lxml").get_text(separator=" ")
    return clean(text)[:max_chars]

def extract_domain(url):
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""




def scrape_adzuna(role):
    """
    Adzuna REST API -- aggregates jobs from Indeed, LinkedIn, company sites.
    Free tier: 1,000 calls/day at developer.adzuna.com
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.warning("  [Adzuna] ADZUNA_APP_ID / ADZUNA_APP_KEY not set -- skipping. See README.md.")
        return []

    leads = []
    for country in ADZUNA_COUNTRIES:
        page = 1
        collected = 0
        while collected < MAX_PER_QUERY:
            per_page = min(50, MAX_PER_QUERY - collected)
            url = (
                "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
                "?app_id={app_id}&app_key={app_key}"
                "&results_per_page={per_page}"
                "&what={role}"
                "&sort_by=date"
                "&content-type=application/json"
            ).format(
                country=country, page=page,
                app_id=ADZUNA_APP_ID, app_key=ADZUNA_APP_KEY,
                per_page=per_page, role=quote(role)
            )
            log.info("  [Adzuna/%s] '%s' page %d", country.upper(), role, page)
            data = fetch_json(url, extra_headers={"Accept": "application/json"})
            if not data:
                break

            jobs = data.get("results", [])
            if not jobs:
                break

            country_label = "United States" if country == "us" else "United Kingdom"
            currency = "$" if country == "us" else "GBP"

            for j in jobs:
                sal_min = j.get("salary_min")
                sal_max = j.get("salary_max")
                if sal_min and sal_max:
                    salary = "{}{:,.0f} - {}{:,.0f}".format(currency, sal_min, currency, sal_max)
                elif sal_min:
                    salary = "{}{:,.0f}+".format(currency, sal_min)
                else:
                    salary = ""

                loc = j.get("location", {})
                location_str = ", ".join(loc.get("display_name", "").split(",")[:2]) or country_label

                company_obj = j.get("company", {})
                company = clean(company_obj.get("display_name", ""))

                leads.append(JobLead(
                    job_title     = clean(j.get("title", "")),
                    company       = company,
                    company_domain= "",
                    location      = location_str,
                    job_url       = j.get("redirect_url", ""),
                    posted_date   = j.get("created", "")[:10],
                    salary        = salary,
                    job_type      = (
                        "Full-time" if j.get("contract_time") == "full_time" else
                        "Part-time" if j.get("contract_time") == "part_time" else
                        clean(j.get("contract_type", ""))
                    ),
                    description   = clean(j.get("description", ""))[:600],
                    source_portal = "Adzuna ({})".format(country_label),
                ))
                collected += 1

            if len(jobs) < per_page:
                break
            page += 1

    log.info("    -> %d results", len(leads))
    return leads
def scrape_reed(role, api_key=""):
    """
    Reed.co.uk REST API -- best for UK roles.
    Free key at: https://www.reed.co.uk/developers/jobseeker
    Set REED_API_KEY env var or pass api_key param.
    """
    key = api_key or os.environ.get("REED_API_KEY", "")
    if not key:
        log.debug("  [Reed] No API key -- skipping. Set REED_API_KEY env var.")
        return []

    url = (
        "https://www.reed.co.uk/api/1.0/search"
        "?keywords={}&locationName=United+Kingdom"
        "&resultsToTake={}&minimumSalary=0"
    ).format(quote(role), MAX_PER_QUERY)

    log.info("  [Reed] '%s'", role)
    data = fetch_json(url, extra_headers={
        "Authorization": "Basic {}".format(key),
        "Accept": "application/json",
    })
    if not data:
        return []

    leads = []
    for j in data.get("results", []):
        employer_url = j.get("employerProfileUrl", "")
        sal_min = j.get("minimumSalary")
        sal_max = j.get("maximumSalary")
        if sal_min and sal_max:
            salary = "GBP{:,.0f} - GBP{:,.0f}".format(sal_min, sal_max)
        elif sal_min:
            salary = "GBP{:,.0f}+".format(sal_min)
        else:
            salary = ""

        leads.append(JobLead(
            job_title     = clean(j.get("jobTitle", "")),
            company       = clean(j.get("employerName", "")),
            company_domain= extract_domain(employer_url) if employer_url else "",
            location      = clean(j.get("locationName", "United Kingdom")),
            job_url       = j.get("jobUrl", ""),
            posted_date   = j.get("date", "")[:10],
            salary        = salary,
            job_type      = "Full-time" if j.get("fullTime") else "Part-time",
            description   = clean(j.get("jobDescription", ""))[:600],
            source_portal = "Reed.co.uk",
        ))
    log.info("    -> %d results", len(leads))
    return leads



def _fetch_linkedin_detail(job_url):
    result = {"company": "", "company_domain": "", "description": "", "job_type": ""}
    soup = fetch_html(job_url)
    if not soup:
        return result

    for sel in [
        "a.topcard__org-name-link",
        "span.topcard__flavor a",
        "div.job-details-jobs-unified-top-card__company-name a",
    ]:
        el = soup.select_one(sel)
        if el:
            result["company"] = clean(el.get_text())
            href = el.get("href", "")
            if href and "linkedin.com/company" not in href:
                result["company_domain"] = extract_domain(href)
            break

    desc_el = soup.select_one(
        "div.show-more-less-html__markup, "
        "section.show-more-less-html, "
        "div[class*='description']"
    )
    if desc_el:
        result["description"] = strip_html_to_text(str(desc_el))

    for badge in soup.select("span.description__job-criteria-text"):
        text = clean(badge.get_text())
        if any(kw in text.lower() for kw in ["full-time", "part-time", "contract", "remote", "hybrid"]):
            result["job_type"] = text
            break

    return result


def scrape_linkedin_jobs(role, location):
    url = (
        "https://www.linkedin.com/jobs/search/"
        "?keywords={}&location={}&sortBy=DD"
    ).format(quote(role), quote(location))
    log.info("  [LinkedIn] '%s' @ '%s'", role, location)
    soup = fetch_html(url)
    if not soup:
        return []

    cards = soup.select("div.base-card")
    leads = []
    for card in cards[:MAX_PER_QUERY]:
        try:
            title_el   = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle, a.hidden-nested-link")
            loc_el     = card.select_one("span.job-search-card__location")
            date_el    = card.select_one("time")
            link_el    = card.select_one("a.base-card__full-link")

            if not title_el or not link_el:
                continue

            href = link_el.get("href", "").split("?")[0]

            lead = JobLead(
                job_title     = clean(title_el.get_text()),
                company       = clean(company_el.get_text()) if company_el else "",
                company_domain= "",
                location      = clean(loc_el.get_text()) if loc_el else location,
                job_url       = href,
                posted_date   = date_el.get("datetime", "") if date_el else "",
                salary        = "",
                job_type      = "",
                description   = "",
                source_portal = "LinkedIn Jobs",
            )

            if DETAIL_FETCH and href:
                detail = _fetch_linkedin_detail(href)
                if detail["company"] and not lead.company:
                    lead.company = detail["company"]
                if detail["company_domain"]:
                    lead.company_domain = detail["company_domain"]
                if detail["description"]:
                    lead.description = detail["description"]
                if detail["job_type"]:
                    lead.job_type = detail["job_type"]

            leads.append(lead)
        except Exception as e:
            log.debug("LinkedIn card error: %s", e)

    log.info("    -> %d results", len(leads))
    return leads




def load_seen_uids(filepath):
    seen = set()
    if not os.path.exists(filepath):
        return seen
    with open(filepath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("job_url", "").strip().lower().split("?")[0]
            if url:
                seen.add(hashlib.md5(url.encode()).hexdigest())
    log.info("Loaded %d existing leads from %s", len(seen), filepath)
    return seen


def append_leads(leads, filepath, seen):
    is_new_file = not os.path.exists(filepath)
    added = 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if is_new_file:
            writer.writeheader()
        for lead in leads:
            if not lead.is_valid():
                continue
            uid = lead.uid()
            if uid in seen:
                continue
            seen.add(uid)
            writer.writerow(asdict(lead))
            added += 1
    return added


# ==========================================================================
# Google Sheets Push
# ==========================================================================

HEADER_ROW = [
    "Job Title", "Company", "Company Domain", "Location", "Job URL",
    "Posted Date", "Salary", "Job Type", "Description", "Source Portal", "Scraped At",
]


def _get_sheet():
    if not GSHEETS_AVAILABLE:
        raise RuntimeError("gspread not installed. Run: pip install gspread google-auth")
    if not os.path.exists(CREDENTIALS):
        raise RuntimeError(
            "Service account key not found: '{}'\n"
            "Place credentials.json in the same folder as scraper.py.".format(CREDENTIALS)
        )
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file(CREDENTIALS, scopes=scopes)
    client = gspread.authorize(creds)
    try:
        spreadsheet = client.open_by_key(SHEET_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        raise RuntimeError(
            "Sheet not found: {}\n"
            "Share the sheet with your service account email.".format(SHEET_ID)
        )
    try:
        worksheet = spreadsheet.worksheet(SHEET_TAB)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_TAB, rows=5000, cols=len(CSV_FIELDS))
        log.info("  Created new tab: '%s'", SHEET_TAB)
    return worksheet


def _existing_urls_in_sheet(worksheet):
    try:
        col_values = worksheet.col_values(5)  # column E = job_url
        return {v.strip().lower().split("?")[0] for v in col_values[1:] if v.strip()}
    except Exception as e:
        log.warning("Could not read existing sheet URLs: %s", e)
        return set()


def push_csv_to_sheets(csv_path=OUTPUT_CSV):
    if not os.path.exists(csv_path):
        log.warning("CSV not found: %s -- nothing to push.", csv_path)
        return 0

    log.info("\n-- Pushing to Google Sheets --")
    log.info("  Sheet ID : %s", SHEET_ID)
    log.info("  Tab      : %s", SHEET_TAB)
    log.info("  CSV      : %s", csv_path)

    try:
        worksheet = _get_sheet()
    except RuntimeError as e:
        log.error("Google Sheets setup error:\n%s", e)
        return 0

    if not worksheet.get_all_values():
        worksheet.append_row(HEADER_ROW, value_input_option="USER_ENTERED")
        log.info("  Wrote header row.")

    existing_urls = _existing_urls_in_sheet(worksheet)
    log.info("  Rows already in sheet: %d", len(existing_urls))

    new_rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("job_url", "").strip().lower().split("?")[0]
            if not url or url in existing_urls:
                continue
            existing_urls.add(url)
            new_rows.append([row.get(field, "") for field in CSV_FIELDS])

    if not new_rows:
        log.info("  No new rows to push -- sheet is up to date.")
        return 0

    BATCH = 500
    pushed = 0
    for i in range(0, len(new_rows), BATCH):
        batch = new_rows[i:i + BATCH]
        worksheet.append_rows(batch, value_input_option="USER_ENTERED")
        pushed += len(batch)
        log.info("  [OK] Pushed batch %d: %d rows", i // BATCH + 1, len(batch))
        if i + BATCH < len(new_rows):
            time.sleep(1.5)

    log.info("  Done. %d new rows added to Google Sheets.", pushed)
    log.info("  -> https://docs.google.com/spreadsheets/d/%s/edit", SHEET_ID)
    return pushed




def run_full(output=OUTPUT_CSV):
    log.info("=" * 60)
    log.info("Job Lead Scraper -- FULL RUN")
    log.info("Roles: %d | Output: %s", len(TARGET_ROLES), output)
    log.info("=" * 60)

    seen  = load_seen_uids(output)
    total = 0

    log.info("\n-- Phase 1: Adzuna API (all roles, US + UK) --")
    for role in TARGET_ROLES:
        batch  = scrape_adzuna(role)
        batch += scrape_reed(role)
        n = append_leads(batch, output, seen)
        total += n
        if n:
            log.info("  [OK] +%d | '%s'", n, role)

    log.info("\n-- Phase 2: LinkedIn (priority roles x locations) --")
    for role in PRIORITY_ROLES:
        for location in LOCATIONS_US_UK:
            batch = scrape_linkedin_jobs(role, location)
            n = append_leads(batch, output, seen)
            total += n
            if n:
                log.info("  [OK] +%d | '%s' @ '%s'", n, role, location)
            time.sleep(random.uniform(5, 12))

    log.info("\n" + "=" * 60)
    log.info("Done. Total new leads added: %d", total)
    log.info("File: %s", os.path.abspath(output))
    log.info("=" * 60)

    push_csv_to_sheets(output)


def run_test(output="test_leads.csv"):
    log.info("=" * 60)
    log.info("Job Lead Scraper -- TEST RUN (Adzuna, 3 roles)")
    log.info("=" * 60)

    test_roles = ["VP Sales", "Head of Growth", "GTM Engineer"]
    seen  = load_seen_uids(output)
    total = 0

    for role in test_roles:
        batch  = scrape_adzuna(role)
        batch += scrape_reed(role)
        n = append_leads(batch, output, seen)
        total += n
        log.info("  '%s' -> %d new leads", role, n)

    log.info("\nTest done. %d leads -> %s", total, os.path.abspath(output))
    push_csv_to_sheets(output)


def run_single_source(source, output=OUTPUT_CSV):
    scrapers = {
        "adzuna":   lambda: [l for r in TARGET_ROLES for l in scrape_adzuna(r)],
        "reed":     lambda: [l for r in TARGET_ROLES for l in scrape_reed(r)],
        "linkedin": lambda: [
            l for r in PRIORITY_ROLES
            for loc in LOCATIONS_US_UK
            for l in scrape_linkedin_jobs(r, loc)
        ],
    }
    if source not in scrapers:
        log.error("Unknown source '%s'. Options: %s", source, list(scrapers))
        return

    log.info("Running single source: %s", source)
    seen  = load_seen_uids(output)
    batch = scrapers[source]()
    n     = append_leads(batch, output, seen)
    log.info("Done. %d new leads -> %s", n, output)
    push_csv_to_sheets(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="B2B Job-Signal Lead Scraper")
    parser.add_argument("--test",         action="store_true", help="Quick Adzuna test (3 roles)")
    parser.add_argument("--source",       type=str, default="", help="adzuna|reed|linkedin")
    parser.add_argument("--output",       type=str, default=OUTPUT_CSV, help="Output CSV path")
    parser.add_argument("--sheets-only",  action="store_true", help="Push existing CSV to Sheets only")
    args = parser.parse_args()

    if args.sheets_only:
        push_csv_to_sheets(args.output)
    elif args.test:
        run_test(args.output if args.output != OUTPUT_CSV else "test_leads.csv")
    elif args.source:
        run_single_source(args.source, args.output)
    else:
        run_full(args.output)