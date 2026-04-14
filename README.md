# AI KYC Query Assistant

AI KYC Query Assistant is a lightweight compliance intelligence platform that lets users ask KYC and risk questions in plain English. The system uses Python to communicate with Gemini, generate safe read-only SQL queries, retrieve data from a compliance database, and return a final report plus a small dashboard summary.

## Overview

This platform is designed for internal compliance and risk teams who want faster access to operational insights without writing SQL manually.

The workflow is:

1. User asks a question in the web interface.
2. Python sends the question and schema context to Gemini.
3. Gemini returns a proposed SQL query.
4. Python validates the SQL for safety.
5. Python queries the database.
6. Python sends the results back to Gemini.
7. Gemini produces a final response and dashboard summary.

## Features

- Natural-language question interface
- Gemini-powered SQL generation
- Python-controlled SQL validation
- Read-only database querying
- Final AI-generated compliance report
- Lightweight dashboard summary
- Gemini and database status indicators
- Suggested question prompts for quick use

## Example Questions

- Show all high-risk clients and summarize the main risk reasons.
- Which CRA reviews are due soon and what follow-up is needed?
- List entities with upcoming compliance deadlines and give me a short risk report.
- Which clients are missing KYC or CDD information?

## Tech Stack

- Python
- Flask
- Gemini API
- SQLAlchemy
- MySQL
- HTML, CSS, JavaScript

## Project Structure

```bash
.
├── ai_kyc_query_app.py
├── templates/
│   └── ai_kyc_query.html
└── README.md
