# Observability

The resilience middleware report what they do in two ways: as stdlib `logging` records, always, and as OpenTelemetry span events when `opentelemetry-api` is installed. Sync and async classes emit the same event names and payloads, so one dashboard covers both.

The logger and event names below are a stable public contract:

| Logger | Events |
|---|---|
| `httpware.retry` | `retry.giving_up`, `retry.budget_refused`, `retry.streaming_refused` |
| `httpware.bulkhead` | `bulkhead.rejected` |
| `httpware.circuit_breaker` | `circuit.opened` (WARNING), `circuit.rejected` (WARNING), `circuit.half_open` (INFO), `circuit.closed` (INFO) |
| `httpware.timeout` | `timeout.exceeded` (WARNING) |

Each log record has an `event` field holding the event name, such as `event="circuit.opened"`, which you can filter on in your log aggregator. Events from `AsyncKeyedCircuitBreaker` and `KeyedCircuitBreaker` also carry `circuit_key`, the circuit they belong to. [Resilience](resilience.md) describes when each event fires.

```python
import logging

# Show the resilience middleware's events
logging.getLogger("httpware.retry").setLevel(logging.WARNING)
logging.getLogger("httpware.bulkhead").setLevel(logging.WARNING)
logging.getLogger("httpware.circuit_breaker").setLevel(logging.INFO)  # INFO for recovery events
logging.getLogger("httpware.timeout").setLevel(logging.WARNING)
```

To also get the events on the active OpenTelemetry span, install the extra:

```bash
pip install httpware[otel]
```

httpware then adds each event to the current span with `trace.get_current_span().add_event(...)`. It never creates spans itself, so the events only show up when something else has started one. The next section shows the minimal setup that does.

## Wiring OpenTelemetry

`httpware[otel]` only installs `opentelemetry-api`. To see the events you also need `opentelemetry-sdk` to collect spans, and `opentelemetry-instrumentation-httpx` to create a span for each HTTP call. httpware's events attach to that span.

A minimal setup with a console exporter, for development:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
HTTPXClientInstrumentor().instrument()
```

With this in place, the instrumentor gives every httpware call an `HTTP <method>` span, and the resilience middleware's events appear on it. httpware itself needs no configuration.

In production, replace `ConsoleSpanExporter` with your OTLP, Jaeger or Zipkin exporter. The [OpenTelemetry Python docs](https://opentelemetry.io/docs/languages/python/) cover the full SDK setup.
