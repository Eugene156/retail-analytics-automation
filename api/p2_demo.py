"""Demo-only read adapter; reuses the existing fixed SQL calculator, no writes."""
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from api.main import Calculator, CalculationRequest, GuardMiddleware, SOURCE_HASH
from api.observability import SafeRequestLogging

PERIOD = {
    "source_file_sha256": SOURCE_HASH,
    "source_time_interpretation": "Europe/London-assumed",
    "period_start_inclusive": "2011-01-28T09:00:00Z",
    "period_end_exclusive": "2011-01-28T10:00:00Z",
    "source_as_of_exclusive": "2011-01-28T10:00:00Z",
}


def project(report, section):
    current = report["current_period"]
    result = {"schema_version": "p2-read-tool-v1", "source_file_sha256": SOURCE_HASH,
              "period": PERIOD, "access": "read-only", section: current[section]}
    if section == "quality":
        result["period_source_rows"] = current["kpis"]["period_source_rows"]
        result["missing_customer_sale_rows"] = current["kpis"]["missing_customer_sale_rows"]
        result["notes"] = "Findings can overlap; missing CustomerID does not exclude valid sales."
    return result


def application():
    dsn = Path("/run/secrets/dsn").read_text().strip()
    parsed = urlsplit(dsn)
    if (parsed.hostname, parsed.username, parsed.path) != ("postgres", "raa_wp2_api", "/raa_wp2_validation"):
        raise RuntimeError("Demo read-only database binding required")
    token = Path("/run/secrets/p2-token").read_text().strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise RuntimeError("Demo read credential required")
    calculator = Calculator(SimpleNamespace(dsn=dsn))
    calculator.ready()
    app = FastAPI(title="P2 demo read tools", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GuardMiddleware, token=token)

    @app.middleware("http")
    async def fixed_surface(request: Request, call_next):
        if request.method != "GET":
            return JSONResponse({"detail": "Read-only methods required"}, status_code=405)
        if request.url.query:
            return JSONResponse({"detail": "Tool arguments are fixed for this demo"}, status_code=422)
        return await call_next(request)

    def read(section):
        try:
            # Preserve decimal SQL numbers as strings; no binary-float arithmetic.
            report = json.loads(calculator.calculate(CalculationRequest(**PERIOD)), parse_float=str)
            return project(report, section)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Demo read tool unavailable") from None

    @app.get("/api/p2/sales-kpis")
    def sales():
        return read("kpis")

    @app.get("/api/p2/data-quality")
    def quality():
        return read("quality")

    app.add_middleware(SafeRequestLogging, service='p2-read-api')
    return app
