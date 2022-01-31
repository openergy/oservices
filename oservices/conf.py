from collections import OrderedDict
import os
import inspect
from contextlib import contextmanager
import logging

from outil.util import load_var, mkdir
from outil.json import load, dump


logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    pass


class ConfField:
    def __init__(self, value=None):
        self._value = value

    @property
    def value(self):
        return self._value


class FileConfField(ConfField):
    def __init__(self, suffix, category, value=None, setattr_fct=None):
        super().__init__(value)
        assert category in ("data", "logging", "static")
        self.suffix = suffix
        self.category = category
        self.setattr_fct = (lambda conf, key, value: setattr(conf, key, value)) if setattr_fct is None else setattr_fct


class DirConfField(ConfField):
    def __init__(self, suffix, category, value=None):
        super().__init__(value)
        assert category in ("data", "logging", "static")
        self.suffix = suffix
        self.category = category


class Configuration:
    CONF_PATH = None
    _manager = None

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            if k.startswith("_"):
                raise ConfigurationError("A configuration variable can't start with _.")
            if hasattr(self.__class__, k):
                raise ConfigurationError("%s is a forbidden configuration variable name (exists in Configuration cls).")
            # we set attribute, bypassing setattr check
            super().__setattr__(k, v)

    def __str__(self):
        msg = "CONF:"
        for k, v in sorted(self.to_dict().items()):
            msg += "\n\t%s: %s" % (k, v)
        return msg

    @property
    def fullname(self):
        return self._manager.conf_fullname

    @contextmanager
    def sync_file(self, file_path):
        conf = self._manager.set_conf_from_file(file_path)
        assert self is conf, "File does not correspond to correct conf (%s instead of %s)" %\
                             (conf.load_fullname, self.fullname)
        try:
            yield
        finally:
            self._manager.to_file(file_path)

    def to_dict(self):
        d = {}
        for var_name in dir(self):
            if var_name.startswith("_"):
                continue
            if hasattr(self.__class__, var_name):  # and (var_name.upper() != var_name):
                continue
            d[var_name] = getattr(self, var_name)
        return d

    def from_dict(self, d):
        """
        var dict only contain variables, but no conf_obj_fullname
        """
        for k, v in d.items():
            if not hasattr(self, k):
                raise KeyError("Configuration does not have attribute '%s'." % k)
            setattr(self, k, v)

    def set_manager(self, manager):
        self._manager = manager

    def standard_configure(self, base_dir_path, service_name, component_name):
        return self._manager.standard_configure(base_dir_path, service_name, component_name)

    def build(self, base_dir_path, service_name, component_name):
        return self._manager.build(base_dir_path, service_name, component_name)

    def __setattr__(self, key, value):
        if not hasattr(self, key):
            raise ConfigurationError("CONF %s has no attribute '%s'." % (self._manager.conf_fullname, key))

        super().__setattr__(key, value)
        self._manager.field_was_set_by_user(key)  # to bypass on standard configure


class ConfigurationManager:
    def __init__(self, conf_type, var_name="CONF"):
        assert conf_type in ("package", "service", "component")
        # todo: find a more elegant way to define var_name
        self._conf_type = conf_type
        self._conf_fullname = inspect.getmodule(inspect.stack()[1][0]).__name__ + "." + var_name
        # (we got module name of previous frame and added var_name)
        self._conf = None
        self._was_set_by_user = set()

    @property
    def conf_fullname(self):
        return self._conf_fullname

    @property
    def conf_keys(self):
        return set(dir(self.__class__)).difference(set(dir(self.__class__.__base__)))

    @property
    def conf(self):
        if self._conf is None:
            self._conf = load_var(self.conf_fullname)
            assert isinstance(self._conf, Configuration), "var_name was improperly set: '%s' (self.conf_fullname) " \
                                                          "should be a conf" % self.conf_fullname
        return self._conf

    def field_was_set_by_user(self, key):
        self._was_set_by_user.add(key)  # to bypass on standard configure

    def to_conf(self):
        # create dict and check everything is ok
        d = {}
        for k in self.conf_keys:
            v = getattr(self, k)
            if not isinstance(v, ConfField):
                raise ConfigurationError("Variable '%s' is not a conf field: '%s' (%s)." % (k, v, type(v)))
            d[k] = v.value
        conf = Configuration(**d)

        conf.set_manager(self)
        return conf

    @classmethod
    def set_conf_from_dict(cls, d):
        """
        Parameters
        ----------
        d: {fullname: 'name.of.conf.CONF', conf: {...},}

        Returns
        -------
        configured CONFIG object
        """
        conf_obj = load_var(d["fullname"])
        conf_obj.from_dict(d["conf"])
        return conf_obj

    @classmethod
    def set_conf_from_file(cls, file_path):
        d = load(file_path)
        obj = cls.set_conf_from_dict(d)
        obj.CONF_PATH = file_path
        return obj

    def to_dict(self):
        return OrderedDict([
            ("fullname", self.conf_fullname),
            ("conf", self.conf.to_dict())
        ])

    def to_file(self, file_path):
        d = self.to_dict()
        dump(d, file_path, indent=4)

    def get_conf_path(self, base_dir_path, service_name, component_name):
        conf_dir_path = os.path.join(base_dir_path, "conf", "%s-%s" % (service_name, component_name))
        return os.path.join(conf_dir_path, self.conf_fullname)

    def standard_configure(self, base_dir_path, service_name, component_name):
        # prepare base_name_l
        base_name_l = dict(
            package=[],
            service=[service_name],
            component=[service_name, component_name]
        )[self._conf_type]

        # get conf object
        conf = load_var(self.conf_fullname)

        # set characterized variables
        for k in self.conf_keys:
            # check was not already set
            if k in self._was_set_by_user:
                continue

            v = getattr(self, k)

            # manage file conf fields and dir conf fields
            if not isinstance(v, (FileConfField, DirConfField)):
                continue
            path = os.path.join(base_dir_path, v.category, "-".join(base_name_l + [v.suffix]))
            if isinstance(v, FileConfField):
                # configure variable
                v.setattr_fct(conf, k, path)
            elif isinstance(v, DirConfField):
                setattr(conf, k, path)

    def build(self, base_dir_path, service_name, component_name):
        # prepare directory structure if needed
        if not os.path.exists(base_dir_path):
            mkdir(base_dir_path)
        for category in ("data", "logging", "static", "conf"):
            path = os.path.join(base_dir_path, category)
            if not os.path.exists(path):
                mkdir(path)

        # build conf
        conf_dir_path = os.path.join(base_dir_path, "conf", "%s-%s" % (service_name, component_name))
        conf_path = os.path.join(conf_dir_path, self.conf_fullname)
        if not os.path.exists(conf_dir_path):
            mkdir(conf_dir_path)

        # make conf directories if needed
        for k in self.conf_keys:
            v = getattr(self, k)
            if isinstance(v, DirConfField):
                dir_path = getattr(self.conf, k)
                if not os.path.exists(dir_path):
                    mkdir(dir_path)

        if os.path.exists(conf_path):
            logger.debug("Conf file already existed and was replaced: %s." % conf_path)
        self.to_file(conf_path)

        return conf_path
