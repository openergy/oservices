import asyncio
import logging
import signal
from asyncio.coroutines import CoroWrapper

from oservices import CONF

from .snippets.oasyncio import raise_exit, ProcessExit, traceback_coro, traceback_partial


logger = logging.getLogger(__name__)


class _AsyncUtilError(Exception):
    pass


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
                logger.critical(
                    "async task raised an exception",
                    exc_info=True
                )
        self._asc.remove(task)

    async def _shut_down(self):
        """
        is entered when shut_down_event has been set
        """
        # call dev async_cleanup
        logger.info(
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
                logger.warning(
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

        logger.info(
            "system is shut down.",
            extra=dict(system=str(self))
        )

    async def start(self, *args, **kwargs):
        if not self.is_off:  # won't start twice
            logger.warning(
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
        logger.info(
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
        logger.info("shut_down was called")
        if not self.is_on:  # won't shut down twice...
            logger.warning(
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
