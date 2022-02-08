"""
opysnippets/processes: 1.0.0

requirements
------------
psutil
"""
import logging
import os
import time
import platform
import threading
import multiprocessing as mp
import signal
import sys
import asyncio
import functools
from concurrent.futures import ProcessPoolExecutor

import psutil

_logger = logging.getLogger(__name__)


class ProcessManagementError(Exception):
    pass


_sys_name = platform.system()  # Windows, Darwin, Linux

########################################################################################################################
#                                       Process cleanup management
# ON LINUX
# -> signals work, but sys.exit is not called if non daemonic children exist
# to tackle the problem, we cleanup all children in the signal handler before calling sys.exit
#
# ON WINDOWS
# -> no foreign process signals, does not work
#
# we create a process with a main thread that starts a daemonic working thread. When a stop event is caught by the main
# thread (inter-process events), the main thread exits => the worker thread exits (it is daemonic)
# problem: sys.exit is never called in worker thread (although it is daemonic) if it contains a non daemonic
# process child.
# to tackle the problem, we terminate all children processes in the main thread, so sys.exit can be called
# in consequence, windows will first terminate children, then call atexit.registered functions. In linux, only
# atexit.register is used
#
# USAGE (multi platform: it has been standardized)
# use register_for_cleanup for children, atexit.terminate for other cleanups
########################################################################################################################

_cleanup_lock = threading.RLock()
_children_objects = []


def _cleanup_child(child):
    if isinstance(child, (mp.Process, GracefulProcess)):
        child.terminate()
    elif isinstance(child, ProcessPoolExecutor):
        child.shutdown()
    else:
        raise ProcessManagementError("unknown child")


def _cleanup_children():
    with _cleanup_lock:
        while len(_children_objects) > 0:
            child = _children_objects.pop()
            _cleanup_child(child)


def register_child_for_cleanup(child):
    if not isinstance(child, (mp.Process, GracefulProcess, ProcessPoolExecutor)):
        raise ProcessManagementError("Unknown object for cleanup registration: %s." % child)
    with _cleanup_lock:
        if child not in _children_objects:
            _children_objects.append(child)


def unregister_child_for_cleanup(child):
    with _cleanup_lock:
        if child in _children_objects:
            _children_objects.remove(child)


def _aio_wrapper(func):
    def wrapped(*args, **kwargs):
        asyncio.set_event_loop(asyncio.new_event_loop())
        return func(*args, **kwargs)
    return wrapped

_MAIN_THREAD_BEAT = 0.1


def _exit_wrapper(func):
    def wrapped(*args, **kwargs):
        register_exit()
        return func(*args, **kwargs)
    return wrapped


def _run_wrapper(func, args, kwargs, stop_event=None):
    """
    stop event is only in windows
    """
    # register exit for all os
    register_exit(is_main_process=False)

    if _sys_name != "Windows":
        return func(*args, **kwargs)
    else:
        t = threading.Thread(target=_aio_wrapper(func), args=args, kwargs=kwargs, daemon=True)
        t.start()

        # wait for thread to finish or stop event to be set
        while True:
            time.sleep(_MAIN_THREAD_BEAT)
            if stop_event.is_set():
                break
            if not t.is_alive():
                break

        # cleanup (if child non daemonic processes exist, sys.exit won't be called...
        _cleanup_children()


def _default_exit(signum, frame):
    """
    only used in main thread (here not on windows)
    """
    # stop all children (so sys.exit can be called properly)
    _cleanup_children()

    # exit
    sys.exit(0)  # if are viewing this traceback: system most probably died normally after a SIGINT or SIGTERM
    # 0 => success code (seems not to de default on all systems - for example debian...)


def register_exit(is_main_process=True):
    """
    if in main thread, will connect sigterm signal to sys.exit.
    De-activates sigint signal if is_subprocess.
    Registers exit on sigint signal if is main process.
    """
    is_main_thread = threading.current_thread() is threading.main_thread()
    _logger.debug("Registering exit, is_main_process=%s, is_main_thread:%s" % (is_main_process, is_main_thread))
    if not is_main_thread:
        return  # exit already registered (if daemon)

    # manage sigint
    if is_main_process:
        # register default exit
        signal.signal(signal.SIGINT, _default_exit)
    else:
        # de-activate sigint
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    # register terminate
    if _sys_name != "Windows":
        # register the asyncio event loop to catch SIGTERMS as well, else a loop running forever cannot be killed.
        asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, functools.partial(_default_exit, None, None))
        signal.signal(signal.SIGTERM, _default_exit)


# prepare context: we force spawn method on linux
_ctx = mp.get_context("spawn")


class GracefulProcess(_ctx.Process):
    _stop_event = None

    def __init__(self, group=None, target=None, name=None, args=None, kwargs=None, daemon=None):
        # defaults
        args = () if args is None else args
        kwargs = {} if kwargs is None else kwargs

        # manage windows
        if _sys_name == "Windows":
            self._stop_event = mp.Event()  # only for windows
        else:
            self._stop_event = None

        # set arguments
        target, args, kwargs = _run_wrapper, (target, args, kwargs, self._stop_event), {}

        # call parent
        super().__init__(group=group, target=target, name=name, args=args, kwargs=kwargs, daemon=daemon)

    def start(self):
        if _sys_name == "Windows":
            self._stop_event.clear()
        super().start()

    def terminate(self):
        if _sys_name == "Windows":
            self._stop_event.set()
        else:
            super().terminate()

    def kill(self):
        os.kill(self.pid, signal.SIGKILL)


# todo: set proc title


class PIDManager:
    def __init__(self, pid_path, name=None):
        self._pid_path = pid_path
        self._name = "no_name" if name is None else name
        self._process_ = None

    @property
    def pid_path(self):
        return self._pid_path

    @property
    def _process(self):
        if self._process_ is None:
            try:
                self._process_ = psutil.Process(self.get())
            except psutil.NoSuchProcess:
                if self.exists():
                    self.remove()
                    logging.getLogger(__name__).warning(
                        "pid file of component does not match a running process pid. File was removed.",
                        extra=dict(
                            pid_manager_name=self._name
                        )
                    )
                self._process_ = False
        return self._process_

    def exists(self):
        return os.path.exists(self._pid_path)

    @property
    def is_on(self):
        return os.path.exists(self._pid_path)

    def check_is_on(self):
        if not self.is_on:
            raise ProcessManagementError(
                "Component '%s' is off. Turn it on before stopping it.\n\t-> No pid file exists at: '%s'" %
                (self._name, self._pid_path))

    def check_is_off(self):
        if self.is_on:
            raise ProcessManagementError(
                "Component '%s' already on. Turn it off before starting it.\n\t-> Pid file exists at: '%s'" %
                (self._name, self._pid_path))

    def register(self):
        with open(self._pid_path, "w") as f:
            f.write(str(os.getpid()))

    def get(self):
        with open(self._pid_path) as f:
            return int(f.read())

    def remove(self):
        if os.path.exists(self._pid_path):
            os.remove(self._pid_path)

    def terminate_process(self):
        if self._process is False:
            return None
        try:
            self._process.terminate()
        except psutil.NoSuchProcess:
            _logger.warning("tried to terminate a process that does no longer exists")

    def wait_for_process(self):
        if self._process is False:
            return None
        self._process.wait()

    def wait_for_on(self):
        # todo: could improve
        while not self.is_on:
            time.sleep(0.1)

    def wait_for_off(self):
        # todo: could improve
        while self.is_on:
            time.sleep(0.1)
