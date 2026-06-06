"""
Prometheus metrics and SLO helpers for concierge workloads.
"""

from __future__ import annotations

from typing import Dict, Optional

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, REGISTRY, generate_latest
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _NoopMetric:
        def labels(self, **kwargs: str) -> "_NoopMetric":
            return self

        def inc(self, amount: float = 1.0) -> None:
            return None

        def observe(self, value: float) -> None:
            return None

        def set(self, value: float) -> None:
            return None

    class _NoopRegistry:
        def collect(self) -> list[object]:
            return []

    def Counter(*args: object, **kwargs: object) -> _NoopMetric:
        return _NoopMetric()

    def Gauge(*args: object, **kwargs: object) -> _NoopMetric:
        return _NoopMetric()

    def Histogram(*args: object, **kwargs: object) -> _NoopMetric:
        return _NoopMetric()

    def generate_latest() -> bytes:
        return b""

    REGISTRY = _NoopRegistry()

from app.core.config import get_settings

settings = get_settings()


HTTP_REQUESTS_TOTAL = Counter(
    "concierge_http_requests_total",
    "Total HTTP requests handled by concierge service",
    ["path_group", "method", "status_class"],
)

HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    "concierge_http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["path_group", "method"],
    buckets=(0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 12),
)

KNOWLEDGE_RETRIEVAL_TOTAL = Counter(
    "concierge_knowledge_retrieval_total",
    "Knowledge retrieval requests by outcome",
    ["outcome"],
)

KNOWLEDGE_RETRIEVAL_LATENCY_SECONDS = Histogram(
    "concierge_knowledge_retrieval_latency_seconds",
    "Knowledge retrieval latency in seconds",
    buckets=(0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 12),
)

VOICE_TURNS_TOTAL = Counter(
    "concierge_voice_turns_total",
    "Total voice concierge turns",
    ["result"],
)

VOICE_TURN_LATENCY_SECONDS = Histogram(
    "concierge_voice_turn_latency_seconds",
    "Voice concierge end-to-end turn latency in seconds",
    buckets=(0.1, 0.2, 0.35, 0.5, 0.75, 1, 1.5, 2, 3, 5, 8, 12, 20),
)

ACTIVE_SESSIONS_GAUGE = Gauge(
    "concierge_active_sessions",
    "Number of active concierge guest sessions",
)

OPEN_ESCALATIONS_GAUGE = Gauge(
    "concierge_open_escalations",
    "Number of open concierge escalations",
)

SLO_BREACH_TOTAL = Counter(
    "concierge_slo_breach_total",
    "SLO threshold breaches by category",
    ["slo"],
)

COMPOSER_OUTCOME_TOTAL = Counter(
    "concierge_composer_outcome_total",
    "Brain composer outcomes by source and health",
    ["composer_source", "fallback_cause"],
)


def _path_group(path: str) -> str:
    if path.startswith("/api/v1/voice"):
        return "voice"
    if path.startswith("/api/v1/knowledge"):
        return "knowledge"
    if path.startswith("/api/v1/concierge"):
        return "concierge"
    if path.startswith("/api/v1/sms"):
        return "sms"
    if path.startswith("/api/v1/phone"):
        return "phone"
    if path.startswith("/api/v1/agents"):
        return "agents"
    if path == "/metrics":
        return "metrics"
    if path == "/health":
        return "health"
    return "other"


def observe_http_request(path: str, method: str, status_code: int, duration_s: float) -> None:
    path_group = _path_group(path)
    status_class = f"{status_code // 100}xx"
    HTTP_REQUESTS_TOTAL.labels(path_group=path_group, method=method, status_class=status_class).inc()
    HTTP_REQUEST_LATENCY_SECONDS.labels(path_group=path_group, method=method).observe(duration_s)
    if duration_s * 1000 > settings.slo_api_latency_ms_threshold:
        SLO_BREACH_TOTAL.labels(slo="api_latency").inc()


def observe_knowledge_retrieval(documents_retrieved: int, retrieval_time_ms: float) -> None:
    outcome = "hit" if documents_retrieved > 0 else "empty"
    KNOWLEDGE_RETRIEVAL_TOTAL.labels(outcome=outcome).inc()
    KNOWLEDGE_RETRIEVAL_LATENCY_SECONDS.observe(max(retrieval_time_ms, 0) / 1000.0)
    if retrieval_time_ms > settings.slo_knowledge_latency_ms_threshold:
        SLO_BREACH_TOTAL.labels(slo="knowledge_latency").inc()
    if documents_retrieved == 0:
        SLO_BREACH_TOTAL.labels(slo="knowledge_empty").inc()


def observe_voice_turn(total_time_ms: float, escalated: bool = False, success: bool = True) -> None:
    result = "escalated" if escalated else ("ok" if success else "error")
    VOICE_TURNS_TOTAL.labels(result=result).inc()
    VOICE_TURN_LATENCY_SECONDS.observe(max(total_time_ms, 0) / 1000.0)
    if total_time_ms > settings.slo_voice_latency_ms_threshold:
        SLO_BREACH_TOTAL.labels(slo="voice_latency").inc()


def observe_composer_outcome(composer_source: str, composer_notes: list) -> None:
    """Record one composer outcome for an inbound brain message.

    Called exactly once per inbound message that reached step 6 of the
    pipeline. Never called on the proactive path (concatenation-by-design)
    or on fast-path early returns (composer never reached).

    fallback_cause derivation::

        llm_*                                          → none       (healthy)
        fallback_empty                                 → empty      (benign, no decisions)
        fallback_concatenation + orchestrator_error    → orchestrator_error  (PAGE)
        fallback_concatenation + no_key* note          → no_keys    (PAGE; May 21-26 sig.)
        fallback_concatenation (other)                 → providers_failed   (WARN)
        composer_source == "none"                      → flag_off   (expected; no alarm)
    """
    if composer_source == "none":
        COMPOSER_OUTCOME_TOTAL.labels(
            composer_source="none", fallback_cause="flag_off"
        ).inc()
        return
    if composer_source.startswith("llm_"):
        cause = "none"
    elif composer_source == "fallback_empty":
        cause = "empty"
    elif composer_source == "fallback_concatenation":
        notes_blob = " ".join(str(n) for n in composer_notes)
        if "composer_orchestrator_error" in notes_blob:
            cause = "orchestrator_error"
        elif "composer_no_key" in notes_blob:
            cause = "no_keys"
        else:
            cause = "providers_failed"
    else:
        cause = "none"
    COMPOSER_OUTCOME_TOTAL.labels(
        composer_source=composer_source, fallback_cause=cause
    ).inc()
    if cause in ("no_keys", "orchestrator_error"):
        SLO_BREACH_TOTAL.labels(slo="composer_fallback").inc()


def update_runtime_gauges(active_sessions: Optional[int] = None, open_escalations: Optional[int] = None) -> None:
    if active_sessions is not None:
        ACTIVE_SESSIONS_GAUGE.set(max(int(active_sessions), 0))
    if open_escalations is not None:
        OPEN_ESCALATIONS_GAUGE.set(max(int(open_escalations), 0))
        if int(open_escalations) > settings.slo_escalation_backlog_threshold:
            SLO_BREACH_TOTAL.labels(slo="escalation_backlog").inc()


def render_metrics() -> tuple[bytes, str]:
    payload = generate_latest()
    return payload, CONTENT_TYPE_LATEST


def get_slo_thresholds() -> Dict[str, float]:
    return {
        "api_latency_ms": float(settings.slo_api_latency_ms_threshold),
        "knowledge_latency_ms": float(settings.slo_knowledge_latency_ms_threshold),
        "voice_latency_ms": float(settings.slo_voice_latency_ms_threshold),
        "empty_retrieval_rate": float(settings.slo_empty_retrieval_rate_threshold),
        "error_rate": float(settings.slo_error_rate_threshold),
        "escalation_backlog": float(settings.slo_escalation_backlog_threshold),
    }


def _counter_total(name: str, labels: Optional[Dict[str, str]] = None) -> float:
    labels = labels or {}
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name != name:
            continue
        for sample in metric.samples:
            if sample.name != name:
                continue
            if all(sample.labels.get(k) == v for k, v in labels.items()):
                total += float(sample.value or 0.0)
    return total


def _gauge_value(name: str) -> float:
    for metric in REGISTRY.collect():
        if metric.name != name:
            continue
        for sample in metric.samples:
            if sample.name == name:
                return float(sample.value or 0.0)
    return 0.0


def get_runtime_snapshot() -> Dict[str, float]:
    total_requests = _counter_total("concierge_http_requests_total")
    total_5xx = _counter_total("concierge_http_requests_total", {"status_class": "5xx"})
    retrieval_total = _counter_total("concierge_knowledge_retrieval_total")
    retrieval_empty = _counter_total("concierge_knowledge_retrieval_total", {"outcome": "empty"})

    return {
        "requests_total": total_requests,
        "http_5xx_total": total_5xx,
        "http_error_rate_since_start": (total_5xx / total_requests) if total_requests > 0 else 0.0,
        "retrieval_total": retrieval_total,
        "retrieval_empty_total": retrieval_empty,
        "empty_retrieval_rate_since_start": (
            retrieval_empty / retrieval_total
        ) if retrieval_total > 0 else 0.0,
        "slo_breach_total": _counter_total("concierge_slo_breach_total"),
        "active_sessions": _gauge_value("concierge_active_sessions"),
        "open_escalations": _gauge_value("concierge_open_escalations"),
    }
