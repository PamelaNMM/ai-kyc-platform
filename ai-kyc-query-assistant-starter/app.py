import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"

load_dotenv(BASE_DIR / ".env")

DB_URI = os.getenv(
    "AI_SQL_DB_URI",
    "mysql+mysqlconnector://username:password@localhost:3306/database_name",
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_ROWS = int(os.getenv("AI_SQL_MAX_ROWS", "100"))
MAX_TABLES = int(os.getenv("AI_SCHEMA_TABLE_LIMIT", "20"))
MAX_COLUMNS = int(os.getenv("AI_SCHEMA_COLUMN_LIMIT", "15"))

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke|"
    r"merge|call|execute|exec|attach|detach|pragma|use|show|describe)\b",
    re.IGNORECASE,
)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
engine = create_engine(DB_URI, pool_pre_ping=True)


def configure_gemini() -> bool:
    if not GEMINI_API_KEY or genai is None:
        return False
    genai.configure(api_key=GEMINI_API_KEY)
    return True


AI_READY = configure_gemini()


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def extract_json(raw_text: str) -> dict[str, Any]:
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Gemini did not return valid JSON.")


def gemini_json(prompt: str) -> dict[str, Any]:
    if not AI_READY:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY.")

    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt)
    raw_text = getattr(response, "text", "") or ""
    return extract_json(raw_text)


def build_schema_summary() -> str:
    inspector = inspect(engine)
    lines: list[str] = []
    for table_name in inspector.get_table_names()[:MAX_TABLES]:
        columns = inspector.get_columns(table_name)[:MAX_COLUMNS]
        fields = [f"{column['name']} ({column['type']})" for column in columns]
        lines.append(f"- {table_name}: {', '.join(fields)}")
    return "\n".join(lines) if lines else "- No tables discovered."


def validate_sql(sql: str) -> str:
    cleaned = (sql or "").strip().rstrip(";")
    if not cleaned:
        raise ValueError("Gemini returned an empty SQL query.")
    if ";" in cleaned:
        raise ValueError("Only a single SQL statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", cleaned, re.IGNORECASE):
        raise ValueError("Only SELECT or WITH queries are allowed.")
    if FORBIDDEN_SQL.search(cleaned):
        raise ValueError("The generated SQL contains forbidden keywords.")
    if re.search(r"\blimit\b", cleaned, re.IGNORECASE) is None:
        cleaned = f"{cleaned}\nLIMIT {MAX_ROWS}"
    return cleaned


def run_query(sql: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        return [
            {key: json_safe(value) for key, value in row._mapping.items()}
            for row in result.fetchall()
        ]


def build_sql_prompt(question: str, schema_summary: str) -> str:
    return f"""
You are a compliance data assistant.
Generate one safe SQL query for a MySQL database.

User question:
{question}

Schema:
{schema_summary}

Rules:
- Return JSON only.
- Use only the provided schema.
- Generate exactly one read-only SQL statement.
- Allowed statements: SELECT or WITH ... SELECT only.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, SHOW, DESCRIBE, CALL, EXECUTE, GRANT, or REVOKE.
- If the request is ambiguous, make the safest reasonable assumption.

Return exactly this JSON structure:
{{
  "sql": "SELECT ...",
  "assumptions": ["short assumption"],
  "business_purpose": "one short sentence"
}}
"""


def build_report_prompt(question: str, sql: str, rows: list[dict[str, Any]]) -> str:
    return f"""
You are a KYC and risk reporting assistant.
Summarize the results in professional business language.

User question:
{question}

Executed SQL:
{sql}

Rows returned: {len(rows)}
Rows sample:
{json.dumps(rows[:25], ensure_ascii=False, indent=2)}

Rules:
- Return JSON only.
- Be factual and use only the provided rows.
- If no rows are returned, say so clearly.
- Keep findings concise.

Return exactly this JSON structure:
{{
  "headline": "short title",
  "summary": "2-4 sentences",
  "key_findings": ["finding 1", "finding 2"],
  "risk_flags": ["optional flag"],
  "recommended_next_steps": ["optional next step"]
}}
"""


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ready = True
        database_error = ""
    except Exception as exc:  # pragma: no cover
        database_ready = False
        database_error = str(exc)

    return jsonify(
        {
            "gemini_ready": AI_READY,
            "database_ready": database_ready,
            "database_error": database_error,
            "model": GEMINI_MODEL,
        }
    )


@app.post("/api/ask")
def ask():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()

    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    if not AI_READY:
        return jsonify({"error": "Gemini is not configured. Set GEMINI_API_KEY."}), 400

    try:
        schema_summary = build_schema_summary()
        sql_payload = gemini_json(build_sql_prompt(question, schema_summary))
        sql = validate_sql(str(sql_payload.get("sql", "")).strip())
        rows = run_query(sql)
        report = gemini_json(build_report_prompt(question, sql, rows))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except SQLAlchemyError as exc:
        return jsonify({"error": f"Database error: {exc}"}), 500
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Processing failed: {exc}"}), 500

    return jsonify(
        {
            "question": question,
            "sql": sql,
            "assumptions": sql_payload.get("assumptions", []),
            "business_purpose": sql_payload.get("business_purpose", ""),
            "row_count": len(rows),
            "rows": rows[:MAX_ROWS],
            "report": {
                "headline": report.get("headline", "KYC/Risk Report"),
                "summary": report.get("summary", ""),
                "key_findings": report.get("key_findings", []),
                "risk_flags": report.get("risk_flags", []),
                "recommended_next_steps": report.get("recommended_next_steps", []),
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5055)
