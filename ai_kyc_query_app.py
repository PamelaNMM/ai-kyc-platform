import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"

DEFAULT_DB_URI = os.getenv(
    "AI_SQL_DB_URI",
    "mysql+mysqlconnector://root:******@localhost:3306/testdb",
)
GEMINI_API_KEY = "AIzaSyCuCChK-SzNOP7p55VwsLUdaTYZarjAtQc"  # os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_ROWS = int(os.getenv("AI_SQL_MAX_ROWS", "100"))
MAX_TABLES_IN_SCHEMA = int(os.getenv("AI_SCHEMA_TABLE_LIMIT", "20"))
MAX_COLUMNS_PER_TABLE = int(os.getenv("AI_SCHEMA_COLUMN_LIMIT", "15"))

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke|"
    r"merge|call|execute|exec|attach|detach|pragma|use|show|describe)\b",
    re.IGNORECASE,
)

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
engine = create_engine(DEFAULT_DB_URI, pool_pre_ping=True)


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
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data

    raise ValueError("Gemini did not return valid JSON.")


def gemini_json(prompt: str) -> dict[str, Any]:
    if not AI_READY:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY.")

    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt)
    raw_text = getattr(response, "text", "") or ""
    return extract_json(raw_text)


def schema_summary() -> str:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    lines: list[str] = []

    for table_name in table_names[:MAX_TABLES_IN_SCHEMA]:
        cols = inspector.get_columns(table_name)[:MAX_COLUMNS_PER_TABLE]
        col_parts = [
            f"{col['name']} ({str(col.get('type', 'unknown'))})"
            for col in cols
        ]
        lines.append(f"- {table_name}: {', '.join(col_parts)}")

    return "\n".join(lines) if lines else "- No tables discovered."


def enforce_read_only_sql(sql: str) -> str:
    cleaned = (sql or "").strip()
    if not cleaned:
        raise ValueError("Gemini returned an empty SQL query.")

    cleaned = cleaned.strip().rstrip(";")

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
        rows = []
        for row in result.fetchall():
            rows.append({key: json_safe(value) for key, value in row._mapping.items()})
        return rows


def build_sql_prompt(question: str, schema_text: str) -> str:
    return f"""
You are a compliance data assistant.
Your job is to create one safe SQL query for a MySQL database.

User question:
{question}

Available schema:
{schema_text}

Rules:
- Return JSON only.
- Use only tables and columns from the provided schema.
- Generate exactly one read-only SQL statement.
- Allowed statements: SELECT or WITH ... SELECT only.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, SHOW, DESCRIBE, CALL, EXECUTE, GRANT, or REVOKE.
- Prefer clear aliases.
- If the question is about KYC, onboarding, client risk, CRA, CDD, BRA, COR, entity, client, or action items, use the most relevant tables.
- If the request is ambiguous, make the safest reasonable assumption and mention it.

Return this JSON schema exactly:
{{
  "sql": "SELECT ...",
  "assumptions": ["short assumption"],
  "business_purpose": "one short sentence"
}}
"""


def build_report_prompt(question: str, sql: str, rows: list[dict[str, Any]]) -> str:
    sample_rows = rows[:25]
    return f"""
You are a KYC and risk reporting assistant.
Turn query results into a concise compliance-style report.

User question:
{question}

Executed SQL:
{sql}

Rows returned: {len(rows)}
Sample rows:
{json.dumps(sample_rows, ensure_ascii=False, indent=2)}

Rules:
- Return JSON only.
- Be factual and only use the provided rows.
- If rows are empty, say that clearly.
- Keep each finding short and professional.
- Do not invent regulatory conclusions.

Return this JSON schema exactly:
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
    return render_template("ai_kyc_query.html")


@app.get("/api/status")
def status():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        db_ok = True
        db_error = ""
    except Exception as exc:  # pragma: no cover
        db_ok = False
        db_error = str(exc)

    return jsonify(
        {
            "gemini_ready": AI_READY,
            "database_ready": db_ok,
            "database_uri": DEFAULT_DB_URI,
            "database_error": db_error,
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
        schema_text = schema_summary()
        sql_response = gemini_json(build_sql_prompt(question, schema_text))
        raw_sql = str(sql_response.get("sql", "")).strip()
        safe_sql = enforce_read_only_sql(raw_sql)
        rows = run_query(safe_sql)
        report = gemini_json(build_report_prompt(question, safe_sql, rows))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except SQLAlchemyError as exc:
        return jsonify({"error": f"Database error: {exc}"}), 500
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": f"Processing failed: {exc}"}), 500

    return jsonify(
        {
            "question": question,
            "schema_preview": schema_text,
            "sql": safe_sql,
            "assumptions": sql_response.get("assumptions", []),
            "business_purpose": sql_response.get("business_purpose", ""),
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
