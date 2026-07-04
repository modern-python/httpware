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

When installed, `_emit_event` calls `trace.get_current_span().add_event(name, attributes=...)` automatically. We never create our own spans, so events only appear if something else creates one — see below for the minimal SDK + instrumentor setup that makes that happen.

## Wiring OpenTelemetry

`httpware[otel]` only ships `opentelemetry-api`. To make the observability events emitted by `AsyncRetry` and `AsyncBulkhead` visible, you also need:

- An **SDK** (`opentelemetry-sdk`) to actually collect spans
- An **HTTP instrumentor** (`opentelemetry-instrumentation-httpx`) so each HTTP call creates a span — `httpware`'s events attach to that span via `trace.get_current_span().add_event(...)`

Minimal setup (console exporter for development):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
HTTPXClientInstrumentor().instrument()
```

After this runs, every `httpware` HTTP call gets an `HTTP <method>` span from the instrumentor, and AsyncRetry/AsyncBulkhead observability events appear as span events on it (no extra configuration needed in `httpware` itself — the events fire whenever an active span is present).

For production, swap `ConsoleSpanExporter` for your OTLP/Jaeger/Zipkin exporter. See the [OpenTelemetry Python docs](https://opentelemetry.io/docs/languages/python/) for the full SDK setup.
