"""Query Prometheus over its HTTP API."""
import httpx

from ..config import settings


def query_prometheus(promql: str) -> str:
    """Run an instant PromQL query and return a compact text result."""
    try:
        r = httpx.get(f"{settings.prometheus_url}/api/v1/query",
                      params={"query": promql}, timeout=10)
        data = r.json()
        if data.get("status") != "success":
            return f"query error: {data}"
        results = data["data"]["result"]
        if not results:
            return "(no data)"
        return "\n".join(
            f"{m.get('metric', {})} -> {m.get('value', ['', ''])[1]}" for m in results[:10]
        )
    except Exception as e:
        return f"ERROR querying Prometheus: {e}"
