"""LTspice result parsers: `.log`, `.raw`, metrics, ranking."""

from emc_assistant.results.log_parser import LogSummary, parse_log
from emc_assistant.results.ranking import RankedVariant, rank_variants
from emc_assistant.results.raw_parser import (
    RawFile,
    RawHeader,
    RawVariable,
    UnsupportedRawFormat,
    extract_to_csv,
    list_traces,
    parse_raw,
)
from emc_assistant.results.metrics import (
    CONDUCTED_EMI_BAND_HZ,
    TraceMetrics,
    compute_trace_metrics,
    max_in_band,
    pick_default_trace,
    summarize_default_metrics,
)

__all__ = [
    "LogSummary",
    "parse_log",
    "RankedVariant",
    "rank_variants",
    "RawFile",
    "RawHeader",
    "RawVariable",
    "UnsupportedRawFormat",
    "extract_to_csv",
    "list_traces",
    "parse_raw",
    "CONDUCTED_EMI_BAND_HZ",
    "TraceMetrics",
    "compute_trace_metrics",
    "max_in_band",
    "pick_default_trace",
    "summarize_default_metrics",
]
