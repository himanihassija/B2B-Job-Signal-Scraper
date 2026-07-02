# B2B Job-Signal Lead Scraper

A Python-based lead generation tool that scrapes high-intent hiring signals from multiple job portals and exports structured company data to CSV and Google Sheets.

The scraper is designed for GTM, sales, marketing, and RevOps teams looking to identify companies actively hiring key revenue roles.

## Features

- Collects jobs from multiple sources:
  - Adzuna API
  - LinkedIn Jobs (public listings)
  - Reed.co.uk API
- Extracts:
  - Job title
  - Company name
  - Company domain
  - Location
  - Salary (when available)
  - Job type
  - Job description
  - Job URL
  - Posted date
- Removes duplicate jobs automatically
- Exports data to CSV
- Syncs new leads directly to Google Sheets
- Supports full runs, test runs, and single-source scraping

---

## Project Structure

```
.
├── scraper.py
├── requirements.txt
├── credentials.json          # Google Service Account
├── .env
├── leads.csv
├── scraper.log
└── README.md
```

---

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd job-signal-scraper
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file.

```env
# Adzuna API
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key

# Reed API (optional)
REED_API_KEY=your_reed_api_key

# Google Sheets
GSHEET_ID=your_sheet_id
GSHEET_TAB=Leads
GOOGLE_CREDENTIALS_PATH=credentials.json
```

---

## Google Sheets Setup

1. Create a Google Cloud Project.
2. Enable the Google Sheets API.
3. Create a Service Account.
4. Download the JSON credentials file.
5. Save it as:

```
credentials.json
```

6. Share your spreadsheet with the service account email.

---

## Usage

### Run the complete scraper

```bash
python scraper.py
```

This will:

- Scrape all configured sources
- Save results to `leads.csv`
- Push new rows to Google Sheets

---

### Test Mode

Runs only a few sample roles using APIs.

```bash
python scraper.py --test
```

Output:

```
test_leads.csv
```

---

### Scrape a Single Source

Adzuna:

```bash
python scraper.py --source adzuna
```

LinkedIn:

```bash
python scraper.py --source linkedin
```

Reed:

```bash
python scraper.py --source reed
```

---

### Push Existing CSV to Google Sheets

```bash
python scraper.py --sheets-only
```

---

## Output Fields

Each lead contains:

| Field | Description |
|--------|-------------|
| job_title | Job title |
| company | Company name |
| company_domain | Company website |
| location | Job location |
| job_url | Direct job posting |
| posted_date | Posting date |
| salary | Salary information |
| job_type | Employment type |
| description | Job description |
| source_portal | Source website |
| scraped_at | Timestamp |

---

## Target Roles

The scraper searches for roles including:

- CRO
- VP Sales
- Head of Sales
- Revenue Operations
- GTM Engineer
- Head of Growth
- VP Marketing
- CMO
- Founder
- CEO
- COO
- CRM Manager
- HubSpot Administrator
- Salesforce Administrator
- SDR Manager
- BDR Manager
- Head of AI
- Solutions Architect

and several other GTM-focused positions.

---

## Data Sources

### Adzuna

- REST API
- US & UK jobs
- Salary information
- Company information

### LinkedIn Jobs

- Public job listings
- Company details
- Job descriptions
- Employment type

### Reed.co.uk

- UK job listings
- Employer information
- Salary data

---

## Duplicate Handling

Jobs are uniquely identified using an MD5 hash of the normalized job URL.

Duplicate entries are automatically skipped during:

- CSV export
- Google Sheets sync

---

## Logging

Execution logs are written to:

```
scraper.log
```

and streamed to the console.

---

## Requirements

- Python 3.9+
- requests
- beautifulsoup4
- lxml
- gspread
- google-auth

Install all dependencies with:

```bash
pip install -r requirements.txt
```

---

## Notes

- LinkedIn scraping relies on publicly accessible job listings and may be subject to rate limiting.
- Reed API requires a valid API key.
- Adzuna provides a free developer tier with daily request limits.
- Introduce delays between requests to reduce the likelihood of being blocked.

---

## License

This project is intended for educational and internal business lead-generation purposes. Please ensure compliance with the Terms of Service of each data source before deploying at scale.
