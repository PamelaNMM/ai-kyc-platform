# AI KYC Query Assistant

AI KYC Query Assistant is a lightweight compliance intelligence platform that lets users ask KYC and risk questions in plain English. Python sends the question to Gemini, Gemini proposes a safe SQL query, Python validates and executes it against a database, and Gemini turns the results into a final report plus a compact dashboard view.

## Overview

This project is designed for internal compliance, onboarding, and risk teams who need quick answers from structured KYC and compliance data without writing SQL manually.

The workflow is:

1. User asks a question in the web interface.
2. Python sends the question and schema context to Gemini.
3. Gemini returns a proposed SQL query in JSON.
4. Python validates the SQL as read-only.
5. Python queries the database.
6. Python sends the query results back to Gemini.
7. Gemini produces a final response and dashboard summary.

## Features

- Natural-language compliance question interface
- Gemini-powered SQL generation
- Python-controlled SQL validation
- Read-only database querying
- Final AI-generated report
- Lightweight dashboard below the response
- Gemini and database status indicators
- Clickable suggested questions

## Example Questions

- Show all high-risk clients and summarize the main risk reasons.
- Which CRA reviews are due soon and what follow-up is needed?
- List entities with upcoming compliance deadlines and give me a short risk report.
- Which clients are missing KYC or CDD information?

## Tech Stack

- Python
- Flask
- SQLAlchemy
- Gemini API
- MySQL
- HTML, CSS, JavaScript

## Project Structure

```text
ai-kyc-query-assistant-starter/
├── .env.example
├── .gitignore
├── README.md
├── app.py
├── requirements.txt
└── templates/
    └── index.html
```

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your environment file:

```bash
copy .env.example .env
```

Set the following values in `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key
AI_SQL_DB_URI=mysql+mysqlconnector://username:password@localhost:3306/database_name
GEMINI_MODEL=gemini-2.5-flash
AI_SQL_MAX_ROWS=100
AI_SCHEMA_TABLE_LIMIT=20
AI_SCHEMA_COLUMN_LIMIT=15
```

## Run

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:5055
```

## Safety Controls

- Only `SELECT` and `WITH ... SELECT` queries are allowed
- Python validates SQL before execution
- Schema-aware prompting is used for Gemini
- A row limit is applied to generated queries
- Gemini never queries the database directly

## Intended Use

This tool is meant for internal decision support. It helps compliance teams analyze KYC and risk data more quickly, but it should not be used as a fully autonomous compliance decision engine.

Human review is recommended for:

- onboarding decisions
- escalations
- risk classification changes
- regulatory or audit-sensitive actions

## Roadmap

- audit logging
- role-based access control
- richer compliance dashboards
- export to Word or PDF
- sanctions or adverse media integration
- document analysis workflows

## License

Choose the license that fits your GitHub repo, such as MIT, Apache 2.0, or Proprietary.
