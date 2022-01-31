"""
opysnippets/streams_and_subprocesses:1.0.0
"""
import sys
import threading
import contextlib
import logging
import subprocess


def _redirect_stream(src, dst, stop_event, freq):
    while not stop_event.is_set():  # read all filled lines
        content = src.readline()
        if content == "":  # empty: break
            break
        dst.write(content)
        if hasattr(dst, "flush"):
            dst.flush()


@contextlib.contextmanager
def redirect_stream(src, dst, freq=0.1):
    stop_event = threading.Event()
    t = threading.Thread(target=_redirect_stream, args=(src, dst, stop_event, freq))
    t.daemon = True
    t.start()
    try:
        yield
    finally:
        stop_event.set()
        t.join()


class LoggerStreamWriter:
    def __init__(self, logger_name, level):
        self._logger = logging.getLogger(logger_name)
        self._level = level

    def write(self, message):
        message = message.strip()
        if message != "":
            self._logger.log(self._level, message)


class UnbufferedStream:
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def run_subprocess(command, cwd=None, stdout=None, stderr=None, shell=False, beat_freq=None):
    """
    Parameters
    ----------
    command: command
    cwd: current working directory
    stdout: output info stream (must have 'write' method)
    stderr: output error stream (must have 'write' method)
    shell: see subprocess.Popen
    beat_freq: if not none, stdout will be used at least every beat_freq (in seconds)
    """
    # prepare variables
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    # run subprocess
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        shell=shell,
        universal_newlines=True
    ) as sub_p:
        # link output streams
        with redirect_stream(sub_p.stdout, stdout), redirect_stream(sub_p.stderr, stderr):
            while True:
                try:
                    sub_p.wait(timeout=beat_freq)
                    break
                except subprocess.TimeoutExpired:
                    stdout.write("subprocess is still running\n")
                    if hasattr(sys.stdout, "flush"):
                        sys.stdout.flush()
        return sub_p.returncode
