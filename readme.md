# Google Reader

Uses Google OAuth API to access your own gmail, then ETL data into google sheets.

Current example:

- Login to email using OAuth, Google Credentials
- Query for Gmail from `no-reply@outpostclimbing.rezeve.com`
- Compiles data retreieved into pandas `dataframe`
- Data compiled will be each record my my gym classes in `outpostclimbing`

## Quickstart

1. Make sure you have already started a new project on Google Cloud Console `https://console.cloud.google.com/`
1. Enable `Gmail API`, `Google Sheets API`, `Google Drive API`
1. Download credentials file i.e. `client_secret_123241-asdadae.apps.googleusercontent.com`
1. Load the credentials file to `/gmail-reader/grrd/secrets/client_secret_123241-asdadae.apps.googleusercontent.com`
1. Run `python cli.py`

## Folder directory

```text
./
├── ggrd/
│   ├── __init__.py
│   ├── gmail.py
│   └── apple_invoice.py
├── cli.py
├── readme.md
├── .gitignore
└── requirements.txt
```
