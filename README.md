# BaluC Report

Flask-based report workspace for generating and downloading report files, with Google Cloud Storage (GCS) support for report persistence and production static asset delivery.

## Tech Stack

- Python 3.12+
- Flask 3
- pandas
- google-cloud-storage

## Project Structure

- app/: Flask application package
- app/blueprints/: route handlers
- app/report_factory/: report generation and async job manager
- app/services/: GCS-related services and storage repository
- app/templates/: Jinja templates
- app/static/: CSS, JS, images, favicon
- tests/: tests
- main.py: runtime entrypoint used locally and by deployment
- deployment.py: Cloud Functions Gen2 deployment helper

## Run Locally

### Customizing ReportSet reports

Each completed base report has **Brand wise Enquery** plus one **By Caption:
caption name** entry for every distinct caption, with individual previews, CSV
downloads, and a combined ZIP download. Blank captions get a `(blank)` entry.
Caption reports contain only rows matching that exact caption. They are generated
on demand, not stored as separate GCS objects. Brand wise Enquery retains its
custom `bu == "--"` filter.

Report Set CSV downloads use short names with the source date range, such as
`brand_enquiry_20260701_20260702.csv` and `caption_altroz_20260701_20260702.csv`.
Individual downloads and ZIP entries use the same names, without internal report
IDs or caption hashes. Names are filesystem-safe, long captions are shortened,
and duplicate names receive numeric suffixes. The date suffix is omitted when the
source filename does not contain a `YYYYMMDD_YYYYMMDD` range.

Edit `brand_wise_enquery(base_df)` or `by_caption(base_df, caption=...)` in
[app/report_factory/report_set.py](app/report_factory/report_set.py) to customize
each report independently. Each function receives a pandas DataFrame loaded from
the original CSV, before display header renaming or percentage formatting, and
returns its own copy as `report_df`. Apply transformations to that copy and return
the resulting DataFrame; preview, CSV, ZIP, and row counts all use these functions.
`REPORT_SET_REPORTS` holds fixed reports; `get_report_set_reports(base_df)` adds
the caption reports dynamically. Caption-specific keys are stable and unique,
including captions with punctuation or non-ASCII characters.
Numeric columns are inferred by pandas (caption is kept as text), while blank cells and literal strings
such as `NA` are retained rather than converted to missing values.

### Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Set environment variables in a local env file.
4. Start the app.

Commands:

	python -m venv .venv
	source .venv/bin/activate
	pip install -r requirements.txt
	python main.py

Default local URL:

- http://127.0.0.1:5001

## Environment Modes

The app reads APP_ENV from environment and maps to config classes:

- development or dev: local development mode
- production or prod: production mode
- testing: test mode

Config source: app/config.py

## Static Asset Behavior

In development:

- Static files are served by Flask from app/static.

In production:

- Static URLs are served from GCS.
- URL format is built from:
  - STATIC_BUCKET
  - STATIC_GCS_PREFIX
  - STATIC_ASSET_BASE_URL (optional explicit override)

If STATIC_ASSET_BASE_URL is empty, the app/deploy flow uses:

- https://storage.googleapis.com/<STATIC_BUCKET>/<STATIC_GCS_PREFIX>

## Required Runtime Variables

Core app/runtime variables:

- APP_ENV
- SECRET_KEY
- APP_PASSWORD (optional; enables app-level password protection when set)
- REPORT_STORAGE_BACKEND
- REPORT_STORAGE_BUCKET_NAME
- REPORT_STORAGE_METADATA_OBJECT
- REPORT_STORAGE_REPORTS_PREFIX
- REPORT_HISTORY_LIMIT
- REPORT_RETENTION_DAYS
- REPORT_STATUS_POLL_SECONDS
- REPORT_TRIGGER_FUNCTION_URL
- STATIC_BUCKET
- STATIC_GCS_PREFIX
- STATIC_ASSET_BASE_URL

Notes:

- Set `APP_PASSWORD` to require a password before users can access app pages. Leave it blank or unset to disable the password gate.
- Use a strong `SECRET_KEY` whenever `APP_PASSWORD` is enabled, because authenticated sessions are stored in Flask's signed session cookie.
- The Flask app triggers report generation via `REPORT_TRIGGER_FUNCTION_URL`.
- The trigger target can be any external HTTP service (for example, a separately deployed `process_in_bq` function).
- Flask has no import/runtime dependency on the `process_in_bq` folder being present in this repository.

## Deployment (Google Cloud Functions Gen2)

Use deployment.py to:

1. Validate or create bucket
2. Apply public object-read IAM role for static hosting
3. Upload app/static to gs://<bucket>/<prefix>
4. Deploy HTTP Cloud Function with runtime env vars

Important:

- deployment.py expects a KEY=VALUE env file.
- Do not point deployment.py to an env file that stores raw JSON blocks.

Recommended deployment env file example (deploy.env):

	DEPLOY_PROJECT_ID=your-project-id
	DEPLOY_REGION=us-central1
	DEPLOY_FUNCTION_NAME=baluc-report-generator
	DEPLOY_ENTRY_POINT=entry_point
	DEPLOY_RUNTIME=python312
	DEPLOY_BUCKET_NAME=your-static-bucket
	DEPLOY_BUCKET_LOCATION=US
	DEPLOY_STATIC_DIR=app/static
	DEPLOY_SOURCE_DIR=.
	DEPLOY_STATIC_GCS_PREFIX=static
	DEPLOY_STATIC_ASSET_BASE_URL=
	DEPLOY_ALLOW_UNAUTHENTICATED=false
	APP_ENV=production
	SECRET_KEY=replace-with-strong-secret
	APP_PASSWORD=replace-with-app-password
	REPORT_STORAGE_BACKEND=gcs
	REPORT_STORAGE_BUCKET_NAME=your-report-storage-bucket

Dry run first:

	python deployment.py --env-file deploy.env --dry-run --dry-run-summary

Deploy:

	python deployment.py --env-file deploy.env

## CLI Options (deployment.py)

Key optional CLI overrides:

- --project-id
- --region
- --function-name
- --entry-point
- --runtime
- --bucket-name
- --bucket-location
- --static-dir
- --static-gcs-prefix
- --static-asset-base-url
- --source-dir
- --allow-unauthenticated
- --dry-run
- --dry-run-summary

## Notes

- Keep secrets out of source control.
- Use a strong SECRET_KEY in production.
- Keep DEPLOY_BUCKET_NAME and STATIC_BUCKET aligned unless you intentionally separate deploy and runtime targets.
