"""OpenTelemetry → LangSmith for LiveKit Agents."""
from __future__ import annotations
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from livekit.agents.telemetry import set_tracer_provider


def init_tracing() -> None:
    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        return
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint="https://api.smith.langchain.com/otel/v1/traces",
                headers={
                    "x-api-key": api_key,
                    "Langsmith-Project": os.getenv("LANGSMITH_PROJECT", "smartcaller-spike"),
                },
            )
        )
    )
    trace.set_tracer_provider(provider)
    set_tracer_provider(provider)
