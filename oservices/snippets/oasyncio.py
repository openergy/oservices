"""
opysnippets/async:1.0.0

Requirements
------------
opysnippets/processes>=1.0.0,<2
"""
import os
import inspect
import traceback
import asyncio
import logging
import types
import concurrent
import platform

from .processes import register_child_for_cleanup

_logger = logging.getLogger(__name__)


class _AsyncUtilError(Exception):
    pass


_thread_pool = None  # shared between threads
_process_pool = None  # shared between threads


def get_loop():
    """
    Rules :
    * 1 loop per thread (prevents from multiple run_until_compete on same loop in sync code)
    * 1 thread pool per process
    * 1 process pool per process
    """
    try:
        return asyncio.get_event_loop()
    except RuntimeError:  # in a thread, loop may not be set
        asyncio.set_event_loop(asyncio.new_event_loop())
        return asyncio.get_event_loop()


def get_thread_pool(max_threads_if_creation=None):
    """

    Parameters
    ----------
    max_threads_if_creation: must be >=1 or None (auto)
        will only be taken into account on pool creation
    """
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = concurrent.futures.ThreadPoolExecutor(max_threads_if_creation)
    return _thread_pool


def get_process_pool(register_as_child=True, max_processes_if_creation=None):
    """
    Parameters
    ----------
    register_as_child
    max_processes_if_creation: 0 (no process pool), n or None (auto)
        will only be taken into account on process creation
    """
    global _process_pool
    if _process_pool is None:
        if (max_processes_if_creation == 0) or (platform.system() == "Windows"):
            _process_pool = get_thread_pool()
        else:
            _process_pool = concurrent.futures.ProcessPoolExecutor(max_processes_if_creation)
            if register_as_child:
                register_child_for_cleanup(_process_pool)
    return _process_pool


def get_function_logger(stack_level=0):
    """
    Returns getLogger(__name__.function_name) where function_name is the calling function
    (or its own calling function if stack_level>0)
    """
    full_name = os.path.splitext(os.path.realpath(inspect.stack()[stack_level + 1][1]))[0]
    parent_dir_path, child_name = os.path.split(full_name)
    module_path = [child_name]
    while child_name != __name__.split(".")[0]:
        parent_dir_path, child_name = os.path.split(parent_dir_path)
        module_path.insert(0, child_name)
    name = ".".join(module_path + [inspect.stack()[stack_level + 1][3]])
    logger = logging.getLogger(name)
    return logger


class AsyncTest:
    def __init__(self, shutdown_timeout=5):
        """
        !! not compatible with nose testing !!
        works for unittests
        """
        self.shutdown_timeout = shutdown_timeout
        _logger.warning("async_test wrapper is not compatible with nose testing framework")

    def __call__(self, f):
        def wrapper(*args, **kwargs):
            coro = asyncio.coroutine(f)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(coro(*args, **kwargs))
            # ensure all tasks have completed
            loop.run_until_complete(asyncio.wait_for(
                asyncio.gather(
                    *asyncio.Task.all_tasks()),
                self.shutdown_timeout
            ))
        return wrapper


class traceback_partial:
    def __init__(self, func, *args, **kwargs):
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def __call__(self):
        try:
            return self._func(*self._args, **self._kwargs)
        except Exception as e:
            raise e.__class__(traceback.format_exc()) from None


async def traceback_coro(coro):
    try:
        return (await coro)
    except Exception as e:
        raise e.__class__(traceback.format_exc()) from None


class ProcessExit(SystemExit):
    code = 1


def raise_exit():
    _logger.warning("SIGINT or SIGTERM received")
    raise ProcessExit()


class SyncWrapper:
    def __init__(self, async_object):
        self._async_object = async_object

    def __getattr__(self, item):
        if asyncio.iscoroutinefunction(getattr(self._async_object, item)):
            return types.MethodType(self.sync_maker(item), self)
        else:
            return getattr(self._async_object, item)

    @staticmethod
    def sync_maker(item):
        def sync_func(self, *args, **kwargs):
            return get_loop().run_until_complete(getattr(self._async_object, item)(*args, **kwargs))

        return sync_func

    @property
    def async_object(self):
        return self._async_object
