# Observability

This page is the stable reference for the logger names, event names, and OpenTelemetry wiring that the resilience middleware emit.

All resilience middleware emit operational events via two channels — stdlib `logging` records (always on) and OpenTelemetry span events (when `opentelemetry-api` is installed). Event names and payloads are identical across sync and async; dashboards built against one class apply unchanged to the other.

Logger names and event names are the stable public contract:

| Logger | Events |
|---|---|
| `httpware.retry` | `retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused` |
| `httpware.bulkhead` | `bulkhead.rejected` |
| `httpware.circuit_breaker` | `circuit.opened` (WARNING), `circuit.rejected` (WARNING), `circuit.half_open` (INFO), `circuit.closed` (INFO) |
| `httpware.timeout` | `timeout.exceeded` (WARNING) |

Each log record carries an `event` field with the event-name string (e.g. `event="circuit.opened"`), usable for log-aggregator filtering. See [resilience.md](resilience.md) for the full event tables per middleware.

```python
import logging

# Enable visibility into resilience operational events
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)
logging.getLogger("httpware.circuit_breaker").setLevel(logging.INFO)  # INFO for recovery events
logging.getLogger("httpware.timeout").setLevel(logging.WARNING)
```

For OTel attribute enrichment on the active span — install the extra:

```bash
pip install httpware[otel]
```

When installed, `_emit_event` calls `trace.get_current_span().add_event(name, attributes=...)` automatically. We never create our own spans; for HTTP-level tracing install `opentelemetry-instrumentation-httpx` separately.
