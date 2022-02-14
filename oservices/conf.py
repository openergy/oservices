from oservices import ConfigurationManager as _ConfigurationManager, ConfField as _ConfField


class _ConfManager(_ConfigurationManager):
    # asyncio
    async_default_shutdown_timeout = _ConfField(value=5)
    asyncio_pool_max_threads = _ConfField()  # must be >=1 or None (auto)
    asyncio_pool_max_processes = _ConfField()  # 0 (no process pool), n or None (auto)


CONF = _ConfManager("package").to_conf()
