# B2B Job-Signal Lead Scraper

A Python scraper that finds B2B sales/GTM leads by monitoring job postings. The idea: when a company is hiring for revenue, sales, marketing, or ops leadership roles, that's a strong buying signal for B2B tools and services targeting those functions.

Pulls job listings across the US and UK, enriches them with company name, salary, location, and job description, deduplicates, and writes everything to a CSV, with optional auto-sync to Google Sheets.

## What it does

- Searches **40+ target job titles** (VP Sales, Head of Growth, RevOps, CRO, Founder, GTM Engineer, HubSpot Admin, etc.), fully configurable
- Pulls from **Adzuna** (aggregates Indeed, LinkedIn, Glassdoor, and direct company postings) and **LinkedIn Jobs** directly
- Optional **Reed.co.uk** integration for deeper UK coverage
- Deduplicates leads across runs (safe to re-run daily/weekly as a cron job)
- Outputs to CSV with: job title, company, location, job URL, posted date, salary, job type, and a job description snippet
- Optional one-line push to a Google Sheet, so leads land somewhere your team can immediately work from

## Why job postings as a lead signal

A company hiring a VP of Sales is investing in growth. A company hiring a HubSpot Administrator just adopted (or is scaling) a CRM. A company hiring an SDR Manager is building out a sales team. These are timing signals that traditional firmographic lead lists miss, this scraper turns "who's hiring for X" into a structured, searchable lead feed.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get a free Adzuna API key

Sign up at [developer.adzuna.com](https://developer.adzuna.com/) — instant, no credit card, 1,000 free calls/day. You'll get an `app_id` and `app_key`.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key
```

The script auto-loads `.env` on startup — no extra dependency needed.

### 4. (Optional) Google Sheets auto-push

If you want leads to land directly in a Google Sheet:

1. Create a project in [Google Cloud Console](https://console.cloud.google.com), enable the **Sheets API** and **Drive API**
2. Create a **Service Account**, generate a JSON key, save it as `credentials.json` in this folder
3. Create a Google Sheet, copy its Sheet ID from the URL, and share the sheet with the service account's email (found in `credentials.json` under `client_email`)
4. Add to `.env`:
   ```
   GSHEET_ID=your_sheet_id
   GOOGLE_CREDENTIALS_PATH=credentials.json
   ```

If you skip this step, the scraper still works fine — it just writes to CSV and logs a message that Sheets push was skipped.

### 5. (Optional) Reed.co.uk for deeper UK coverage

Free key at [reed.co.uk/developers/jobseeker](https://www.reed.co.uk/developers/jobseeker). Add `REED_API_KEY=your_key` to `.env`.

## Usage

```bash
# Quick test — 3 roles, Adzuna only, fast validation
python scraper.py --test

# Full run — all 40+ roles, all sources, writes to leads.csv
python scraper.py

# Push an existing leads.csv to Google Sheets without re-scraping
python scraper.py --sheets-only

# Run a single source for debugging
python scraper.py --source adzuna
python scraper.py --source linkedin
python scraper.py --source reed
```

## Configuration

Everything you'd want to change lives at the top of `scraper.py`:

| Variable | What it controls |
|---|---|
| `TARGET_ROLES` | The 40+ job titles searched (fully editable list) |
| `PRIORITY_ROLES` | Subset used for the slower LinkedIn HTML scraper |
| `ADZUNA_COUNTRIES` | Country codes to search (`us`, `gb`, `au`, `ca`, `de`, `fr`, `in`, etc — [full list](https://developer.adzuna.com/docs)) |
| `LOCATIONS_US_UK` | Locations used for LinkedIn search |
| `MAX_PER_QUERY` | Max results per role per source |
| `REQUEST_DELAY` | Delay range between requests (be polite to the sites you scrape) |

To target a different market or different buyer persona, just edit `TARGET_ROLES` and `ADZUNA_COUNTRIES` — no other code changes needed.

## Output

CSV columns: `job_title, company, company_domain, location, job_url, posted_date, salary, job_type, description, source_portal, scraped_at`

Re-running the scraper is safe — it deduplicates against existing rows in `leads.csv` (or the Google Sheet) by job URL, so you can schedule it as a daily/weekly cron job without creating duplicate leads.

## A note on scraping etiquette

This project includes deliberate request delays and rotating user agents to avoid hammering job sites. LinkedIn's public job search pages are scraped respectfully (no login, no automation of authenticated actions) — please keep it that way if you extend this. Always check a site's terms of service before scraping at scale.

## License

MIT — use it, fork it, adapt it for your own ICP.
