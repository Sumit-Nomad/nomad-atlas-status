# nomad-atlas-status

Scheduled scraper that reads each store's Zomato/Swiggy enabled/disabled state from
UrbanPiper Atlas and posts it to an Apps Script webhook. No business data lives in this repo;
all endpoints and keys are GitHub Actions secrets.

Secrets (Settings -> Secrets and variables -> Actions):
`DASHBOARD_URL`, `DASHBOARD_INGEST_KEY`, `NOMAD_STATUS_WEBHOOK_URL`, `NOMAD_STATUS_WEBHOOK_TOKEN`
(token optional).

The Atlas login session is saved by running `save_atlas_session.py` locally (a human logs in);
it is uploaded to the dashboard's Apps Script, not stored here.
