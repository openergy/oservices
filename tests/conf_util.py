import operator

from oservices import ConfigurationManager, ConfField, FileConfField, DirConfField


class _SimpleConfManager(ConfigurationManager):
    int = ConfField(value=1)
    str = ConfField(value="str")

simple_conf_manager = _SimpleConfManager("package", var_name="simple_conf")
simple_conf = simple_conf_manager.to_conf()


class _WithHDConf(ConfigurationManager):
    int = ConfField(value=1)
    str = ConfField(value="str")
    log_file_path = FileConfField("main.log", "logging")
    db_dir_path = DirConfField("adb", "data")
    sqlite_db = FileConfField("db.sqlite3", "data",
                              value=dict(ENGINE='django.db.backends.sqlite3', NAME=None),
                              setattr_fct=(lambda conf, key, value: operator.setitem(
                                      getattr(conf, key), "NAME", value)))

with_hd_conf_manager = _WithHDConf("component", "with_hd_conf")
with_hd_conf = with_hd_conf_manager.to_conf()

