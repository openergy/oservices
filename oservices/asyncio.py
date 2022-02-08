import concurrent
import platform

from .processes import register_child_for_cleanup


_thread_pool = None  # shared between threads
_process_pool = None  # shared between threads


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
