import os
import inspect
import traceback
import asyncio
from asyncio.coroutines import CoroWrapper
import logging
import types
import concurrent
import platform
import signal

from oservices import CONF
from ..snippets.processes import register_child_for_cleanup


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


def get_thread_pool():
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = concurrent.futures.ThreadPoolExecutor(CONF.asyncio_pool_max_threads)
    return _thread_pool


def get_process_pool(register_as_child=True):
    global _process_pool
    if _process_pool is None:
        if (CONF.asyncio_pool_max_processes == 0) or (platform.system() == "Windows"):
            _process_pool = get_thread_pool()
        else:
            _process_pool = concurrent.futures.ProcessPoolExecutor(CONF.asyncio_pool_max_processes)
            if register_as_child:
                register_child_for_cleanup(_process_pool)
    return _process_pool


def get_function_logger(stack_level=0):
    """
    Returns getLogger(__name__.function_name) where function_name is the calling function
    (or its own calling function if stack_level>0)
    """
    full_name = os.path.splitext(os.path.realpath(inspect.stack()[stack_level+1][1]))[0]
    parent_dir_path, child_name = os.path.split(full_name)
    module_path = [child_name]
    while child_name != __name__.split(".")[0]:
        parent_dir_path, child_name = os.path.split(parent_dir_path)
        module_path.insert(0, child_name)
    name = ".".join(module_path + [inspect.stack()[stack_level+1][3]])
    logger = logging.getLogger(name)
    return logger


def async_test(f):
    """
    !! not compatible with nose testing !!
    works for unittests
    """
    _logger.warning("async_test wrapper is not compatible with nose testing framework")

    def wrapper(*args, **kwargs):
        coro = asyncio.coroutine(f)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(coro(*args, **kwargs))
        # ensure all tasks have completed
        loop.run_until_complete(asyncio.wait_for(asyncio.gather(*asyncio.Task.all_tasks()),
                                                 CONF.async_default_shutdown_timeout))

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


class OnOffSystem:
    ON = "on"
    OFF = "off"
    SHUTTING_DOWN = "shutting_down"
    # todo: optimize (see all examples)

    def __init__(self, loop=None):
        self._loop = asyncio.get_event_loop() if loop is None else loop
        self._is_on_event = asyncio.Event(loop=loop)
        self._shut_down_event = asyncio.Event(loop=loop)
        self._is_off_event = asyncio.Event(loop=loop)
        self._asc = set()  # async tasks

        self._set_state(self.OFF)
        self._shut_down_args, self._shut_down_kwargs = (), {}

    @property
    def state(self):
        """
        Can only be in one state at a time: on -> shutting down -> off
        """
        return self._state

    @property
    def is_on(self):
        return self._is_on_event.is_set()

    @property
    def is_shutting_down(self):
        return self._shut_down_event.is_set()

    @property
    def is_off(self):
        return self._is_off_event.is_set()

    async def wait_for_on(self):
        return await self._is_on_event.wait()

    async def wait_for_shutting_down(self):
        return await self._shut_down_event.wait()

    async def wait_for_off(self):
        return await self._is_off_event.wait()

    def _set_state(self, state):
        if state == self.ON:
            self._is_on_event.set()
            self._shut_down_event.clear()
            self._is_off_event.clear()
        elif state == self.SHUTTING_DOWN:
            self._is_on_event.clear()
            self._shut_down_event.set()
            self._is_off_event.clear()
        elif state == self.OFF:
            self._is_on_event.clear()
            self._shut_down_event.clear()
            self._is_off_event.set()
        else:
            raise _AsyncUtilError("Unknown state.")
        self._state = state

    async def _store_and_clear_task(self, task):
        self._asc.add(task)
        await asyncio.wait({task}, loop=self._loop)
        e = task.exception()
        if e is not None:
            try:
                raise e
            except:
                _logger.critical(
                    "async task raised an exception",
                    exc_info=True
                )
        self._asc.remove(task)

    async def _shut_down(self):
        """
        is entered when shut_down_event has been set
        """
        # call dev async_cleanup
        _logger.info(
            "shutting down system",
            extra=dict(system=str(self))
        )
        try:
            await self._async_cleanup(*self._shut_down_args, **self._shut_down_kwargs)
        except TypeError:
            raise _AsyncUtilError(
                "Wrong args and/or kwargs given to shut_down (must be compatible with _async_cleanup function)")

        # wait for tasks to stop
        if len(self._asc) > 0:
            done, pending = await asyncio.wait(
                self._asc,
                timeout=CONF.async_default_shutdown_timeout, loop=self._loop)
            if len(pending) > 0:
                _logger.warning(
                    "some tasks are still pending after timeout although they shouldn't",
                    extra=dict(
                        system=str(self),
                        timeout=CONF.async_default_shutdown_timeout,
                        pending_tasks="\n".join([str(p) for p in pending])
                    )
                )

        # call dev sync_cleanup
        try:
            self._sync_cleanup(*self._shut_down_args, **self._shut_down_kwargs)
        except TypeError:
            raise _AsyncUtilError(
                "%s: wrong args and/or kwargs given to shut_down (must be compatible with _sync_cleanup function)."
                "\nargs: %s\nkwargs: %s" % (self.__class__.__name__, self._shut_down_args, self._shut_down_kwargs)
            )
        self._shut_down_args, self._shut_down_kwargs = (), {}

        # declare off state
        self._set_state(self.OFF)

        _logger.info(
            "system is shut down.",
            extra=dict(system=str(self))
        )

    async def start(self, *args, **kwargs):
        if not self.is_off:  # won't start twice
            _logger.warning(
                "asked to start although not off",
                extra=dict(
                    state=self.state,
                    system=str(self)
                )
            )

        # call dev setup
        # todo: try except to make easy to understand error
        try:
            await self._setup(*args, **kwargs)
        except TypeError:
            raise _AsyncUtilError("Wrong args and/or kwargs given to start (must be compatible with _setup function).")

        # set state on
        self._set_state(self.ON)

        # wait for shut down event
        await self._shut_down_event.wait()
        _logger.info(
            "shut down state was set, wait finished",
            extra=dict(system=str(self))
        )
        # shut down
        await self._shut_down()

    def run(self, f, handle_signals=False):
        if handle_signals:
            try:
                self._loop.add_signal_handler(signal.SIGINT, raise_exit)
                self._loop.add_signal_handler(signal.SIGTERM, raise_exit)
            except NotImplementedError:  # pragma: no cover
                # add_signal_handler is not implemented on Windows
                pass

        try:
            self._loop.run_until_complete(self.start())
        except (KeyboardInterrupt, ProcessExit):
            print("KeyboardInterrupt")
            if handle_signals:
                # un-register the signal
                try:
                    self._loop.remove_signal_handler(signal.SIGINT)
                    self._loop.remove_signal_handler(signal.SIGTERM)
                except NotImplementedError:
                    pass

        self._loop.run_until_complete(f())

    def shut_down(self, *args, **kwargs):
        """
        this function may be called from inside a _ensure_future task
        """
        _logger.info("shut_down was called")
        if not self.is_on:  # won't shut down twice...
            _logger.warning(
                "asked to shut_down although not on",
                extra=dict(
                    state=self.state,
                    system=str(self)
                )
            )
            return

        self._shut_down_args = args
        self._shut_down_kwargs = kwargs
        self._set_state(self.SHUTTING_DOWN)

    # developer methods

    async def _setup(self):
        """
        to be overridden
        """
        pass

    async def _async_cleanup(self, *args, **kwargs):
        """
        to be overridden
        """
        pass

    def _sync_cleanup(self, *args, **kwargs):
        """
        to be overridden
        """
        pass

    def _ensure_future(self, coro):
        """
        traceback is managed
        task is stored to be gathered at shut_down
        at shut down, if tasks are remaining, message will not be explicit => use _call_and_ensure_future if possible
        """
        task = asyncio.ensure_future(traceback_coro(coro), loop=self._loop)
        asyncio.ensure_future(self._store_and_clear_task(task), loop=self._loop)
        return task

    def _call_and_ensure_future(self, coro_func, *args, **kwargs):
        """
        traceback is managed
        task is stored to be gathered at shut_down
        at shut down, tasks messages are ok
        """
        coro = CoroWrapper(traceback_partial(coro_func, *args, **kwargs)(), func=coro_func)
        task = asyncio.ensure_future(coro, loop=self._loop)
        asyncio.ensure_future(self._store_and_clear_task(task), loop=self._loop)
        return task


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
