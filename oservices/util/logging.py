"""
Openergy's logging library.
Logging should be done using python's logging library, like below:

logger = logging.get_logger(__name__)
logger.warning(<message>, extra=<properties>)

where <message> is a generic log message (it should not contain any variable)
and <properties> is a dictionnary containing user-defined information useful for debugging (as an example:
{'client_ip': '10.0.0.1', 'user_id': 12345, analysis_id: 21323123})

Properties must be str, int or float.
For message, 1st sentence is lowercase. If no other sentence, no point. Else put a point and use uppercase for beginning
of other sentences.

Handlers using the TextFormatter class as a formatter will get the properties at the end of the logging message.

The AzureLoggingHandler is used to have logs sent to azure application insights.
"""
import logging
import textwrap
import socket
from applicationinsights.logging import LoggingHandler
from aiohttp.web_log import AccessLogger
try:
    from django.core.handlers.wsgi import WSGIRequest
except ImportError:
    WSGIRequest = None

RESERVED_ATTRS = (
    'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'levelname', 'levelno', 'lineno',
    'module', 'msecs', 'message', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'stack_info',
    'thread', 'threadName'
)


class LoggingTextFormatter(logging.Formatter):
    def format(self, record):
        """Formats a log record and serializes to json"""
        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)
        s = self.formatMessage(record)
        # add the extra fields
        if s[-1:] != "\n":
            s = s + "\n"
        s = s + textwrap.indent(
            '\n'.join([f'{key} : {record.__dict__[key]}' for key in record.__dict__ if key not in RESERVED_ATTRS]),
            '  |'
        )
        if record.exc_info:
            # Cache the traceback text to avoid converting it multiple times
            # (it's constant anyway)
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            if s[-1:] != "\n":
                s = s + "\n"
            s = s + record.exc_text
        if record.stack_info:
            if s[-1:] != "\n":
                s = s + "\n"
            s = s + self.formatStack(record.stack_info)
        return s


class AzureLoggingHandler(LoggingHandler):
    def __init__(self, instrumentation_key, component_name, *args, **kwargs):
        self.hostname = socket.gethostname()
        self.component_name = component_name
        super().__init__(instrumentation_key, *args, **kwargs)

    def emit(self, record):
        """Emit a record.

        If a formatter is specified, it is used to format the record. If exception information is present, an Exception
        telemetry object is sent instead of a Trace telemetry object.

        Args:
            record (:class:`logging.LogRecord`). the record to format and send.
        """
        # the set of properties that will ride with the record
        properties = dict(
            process=record.processName,
            module=record.name,
            filename=record.filename,
            line_number=record.lineno,
            level=record.levelname,
            hostname=self.hostname,
            component=self.component_name,
            **dict((f'_{key}', record.__dict__[key]) for key in record.__dict__ if key not in RESERVED_ATTRS)
        )

        # Bad hack for django, find a better way...
        if WSGIRequest is not None and isinstance(properties.get("_request"), WSGIRequest):
            properties["_request"] = str(properties["_request"])

        # if we have exec_info, we will use it as an exception
        if record.exc_info:
            self.client.track_exception(*record.exc_info, properties=properties)
        else:
            # if we don't simply format the message and send the trace
            formatted_message = self.format(record)
            self.client.track_trace(formatted_message, properties=properties, severity=record.levelname)
        # We flush immediately for anything above warnings (for info, etc. will be flushed when the queue has 500 msgs)
        if record.levelno >= logging.WARNING:
            self.client.flush()


# extra methods
EXTRA_METHODS = '%s %a %Tf %b %r %{User-Agent}i'


class CustomAccessLogClass(AccessLogger):
    """
    Workaround for logging errors 500 to logger.error instead of logger.info.
    The code below is a light modification of aiohttp.helpers.AccessLogger:
    """
    def __init__(self, logger, log_format=AccessLogger.LOG_FORMAT):
        """Initialise the logger.

        logger is a logger object to be used for logging.
        log_format is an string with apache compatible log format description.

        """
        super().__init__(logger, log_format=log_format)

        _compiled_format = AccessLogger._FORMAT_CACHE.get(EXTRA_METHODS)
        if not _compiled_format:
            _compiled_format = self.compile_format(EXTRA_METHODS)
            AccessLogger._FORMAT_CACHE[EXTRA_METHODS] = _compiled_format

        _, self._extra_methods = _compiled_format

    def _format_line_extra(self, request, response, time):
        return ((key, method(request, response, time))
                for key, method in self._extra_methods)

    def log(self, request, response, time):
        try:
            fmt_info = self._format_line(request, response, time)
            extra_info = self._format_line_extra(request, response, time)

            values = [value for key, value in fmt_info]
            extra = dict()
            for key, value in extra_info:
                if key.__class__ is str:
                    extra[key] = value
                else:
                    if key[0] not in extra:
                        extra[key[0]] = f'{key[1]}: {value}'
                    else:
                        extra[key[0]].append('\n'f'{key[1]}: {value}')

            if response.status // 100 == 5:
                self.logger.error(self._log_format % tuple(values), extra=extra)
            else:
                self.logger.info(self._log_format % tuple(values), extra=extra)
        except Exception:
            self.logger.exception("Error in logging")


