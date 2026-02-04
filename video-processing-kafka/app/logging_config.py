import logging
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.trace_id = "-"
        return True


def configure_logging(service_name: str) -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format=(
            "%(asctime)s %(levelname)s "
            f"{service_name} "
            "trace=%(trace_id)s "
            "%(name)s: %(message)s"
        ),
    )
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(TraceIdFilter())


class TraceAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        trace_id = kwargs.pop("trace_id", "-")
        return msg, {"extra": {"trace_id": trace_id}}


def get_logger(name: str) -> TraceAdapter:
    return TraceAdapter(logging.getLogger(name), {})
