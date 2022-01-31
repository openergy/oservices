import inspect
import importlib
from abc import abstractmethod


class DataContainer:
    def __init__(self):
        super().__setattr__("_data", {})

    def __setattr__(self, key, value):
        self._data[key] = value

    def __getattr__(self, item):
        assert item in self._data, "no variable named: '%s'" % item
        return self._data[item]

    def __str__(self):
        return str(self._data)


class SettingsField:
    def __init__(self, optional=False, default_value=None):
        """
        Parameters
        ----------
        optional
        default_value: only used if optional=True

        User is free to use settings or not, no default value will automatically be applied.
        """
        self.optional = optional
        self.default_value = default_value


class SettingsManager:
    def __init__(self, settings_module_name="settings"):
        # load settings
        settings = None
        try:
            settings = importlib.import_module(settings_module_name)
            self._settings_where_loaded = True
        except ImportError:
            self._settings_where_loaded = False

        if self._settings_where_loaded:
            # load settings
            self._apply_settings(settings)

    def _apply_settings(self, settings_module):
        # prepare data container
        self.settings = DataContainer()

        # iter through class fields
        for k in set(dir(self.__class__)):
            v = getattr(self, k)

            if inspect.ismethod(v):  # only look at variables
                continue

            if k[:1] == "_":  # skip private variables
                continue

            if not isinstance(v, SettingsField):  # only consider SettingsFields
                continue

            if not v.optional:
                assert hasattr(settings_module, k), "required variable not found in settings file: '%s'" % k

            setattr(self.settings, k, getattr(settings_module, k, v.default_value))

    @abstractmethod
    def propagate_settings(self, component=None, component_arg=None):
        """
        Propagate settings to conf
        """
        raise NotImplemented
