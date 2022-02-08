import os
import logging
import traceback
import copy
import inspect
import json
import tempfile
import sys

from .processes import GracefulProcess, register_exit
from .snippets.streams_and_subprocesses import run_subprocess
from .snippets.load_var import load_var
from .configuration_management import ConfigurationManager


logger = logging.getLogger(__name__)


class ComponentError(Exception):
    pass


class Component:
    _INFO = "__info__.json"
    _LOAD_FULLNAME = "_load_fullname"
    _NAME = "_name"

    def __init__(self, service_name, name, default_confs, load_name="COMPONENT", load_kwargs=None):
        """
        load_name: name of the variable in which object is stored
        load_kwargs:
            - if None, the variable in which object is stored will be loaded directly
            - if dict, the variable in which object is stored will be called with load_kwargs
        default_confs: only used for build, not for setup
        """
        self._service_name = service_name
        self._name = name
        self._load_fullname = inspect.getmodule(inspect.stack()[1][0]).__name__ + "." + load_name
        self._load_kwargs = load_kwargs
        # get get module name of previous stack
        self._confs = set() if default_confs is None else set(default_confs)

        # automatic variables
        self._is_setup = False
        self._conf_dir_path = None

    # ---------------------------------- CONFIGURATION MANAGEMENT ------------------------------------------------------
    @property
    def name(self):
        return self._name

    @property
    def service_name(self):
        return self._service_name

    def change_name(self, new_name):
        self._name = new_name

    def add_conf(self, conf):
        self._confs.add(conf)

    @property
    def load_fullname(self):
        return self._load_fullname

    @property
    def conf_dir_path(self):
        return self._conf_dir_path

    @conf_dir_path.setter
    def conf_dir_path(self, value):
        assert self._conf_dir_path is None, "Conf dir path was already set, can't re-set."
        self._conf_dir_path = value

    def standard_conf_dir_path(self, base_dir_path):
        return os.path.join(base_dir_path, "conf", "%s-%s" % (self._service_name, self._name))

    @classmethod
    def configure_component(cls, conf_dir_path):
        """
        Returns
        -------
        configured component
        """
        # check fullname file exists
        info_path = os.path.join(conf_dir_path, cls._INFO)
        assert os.path.exists(info_path), "Component conf dir must have a '%s' file (%s)." % (cls._INFO, conf_dir_path)

        # configure all configurations
        for name in os.listdir(conf_dir_path):
            if name == cls._INFO:
                continue
            ConfigurationManager.set_conf_from_file(os.path.join(conf_dir_path, name))

        # get component object
        with open(info_path) as f:
            d = json.load(f)
        load_fullname = d[cls._LOAD_FULLNAME]
        name = d[cls._NAME]
        component = load_var(load_fullname)
        component.change_name(name)

        # set conf_dir_path
        component._conf_dir_path = conf_dir_path  # we don't call public setter to bypass check

        return component

    def standard_configure(self, base_dir_path, build=True):
        for conf in self._confs:
            conf.standard_configure(base_dir_path, self._service_name, self._name)
        if build:
            return self.build(base_dir_path)

    # ------------------------------------------ SETUP MANAGEMENT ------------------------------------------------------
    def setup(self):
        # log that setup is performed
        stack = "".join(traceback.format_stack()[:-1])

        # stack_tree = inspect.stack()[1][1] + ":" + inspect.stack()[1][3]

        if self.is_setup:
            # todo: settup shouldn't be performed twice, and 1st logger should be warning (was put to debug because
            # happens all the time...)
            logger.debug("Setup was already performed, will not setup twice (class: %s)." % self.load_fullname)
            logger.debug("Last log origin:\n%s" % stack)
            return

        # we freeze configuration now
        self._is_setup = True

        # LOGGING
        logger.info(
            "performing logging setup",
            extra=dict(class_name=self.load_fullname)
        )
        self.configure_logging()

        # DJANGO
        # setup django
        if self.django_d is not None:
            logger.info(
                "performing django setup",
                extra=dict(class_name=self.load_fullname)
            )
            import django
            from django.conf import settings

            # we use a function and deepcopy to unlink from CONFIG (django may use unexpectedly)
            settings.configure(**copy.deepcopy(self.django_d))
            django.setup()

    @property
    def is_setup(self):
        return self._is_setup

    # ------------------------------------- INITIALIZATION MANAGEMENT --------------------------------------------------
    @staticmethod
    def initialize_django_files(with_db=True, with_static=True):
        from odjango.django_safe import initialize_django_files
        if with_db or with_static:
            initialize_django_files(migrations=with_db, static=with_static)

    @classmethod
    def initialize_component_django_files(cls, conf_dir_path, with_db=True, with_static=True):
        # configure
        component = cls.configure_component(conf_dir_path)

        # setup
        component.setup()

        # initialize
        component.initialize_django_files(with_db=with_db, with_static=with_static)

        return component

    @classmethod
    def initialize_django_files_in_process(cls, conf_dir_path, with_db=True, with_static=True):
        p = GracefulProcess(target=cls.initialize_component_django_files, args=(conf_dir_path,),
                            kwargs=dict(with_db=with_db, with_static=with_static))
        p.start()
        return p

    # ------------------------------------------ BUILD MANAGEMENT ------------------------------------------------------
    def build(self, base_dir_path):
        """
        Parameters
        ----------
        base_dir_path

        Returns
        -------
        writes all configuration files

        """
        for conf in self._confs:
            conf.build(base_dir_path, self._service_name, self._name)
        with open(os.path.join(self.standard_conf_dir_path(base_dir_path), self._INFO), "w") as f:
            json.dump({self._LOAD_FULLNAME: self.load_fullname, self._NAME: self._name}, f)
        return self.standard_conf_dir_path(base_dir_path)

    # -------------------------------------------- RUN MANAGEMENT ------------------------------------------------------
    def start(self):
        """
        setup and run
        """
        # setup
        self.setup()

        # run
        self.run()

    @classmethod
    def start_component(cls, conf_dir_path, is_main_process=False):
        """
        configure, and start component (often used in a process)
        """
        # register exit if not main process
        if not is_main_process:
            register_exit(is_main_process=False)

        # configure
        component = cls.configure_component(conf_dir_path)

        # start
        try:
            component.start()
        except Exception as e:
            raise e.__class__("Error caught in component '%s':\n%s" % (component.name, traceback.format_exc())) from None

    @classmethod
    def start_in_process(cls, conf_dir_path):
        p = GracefulProcess(target=cls.start_component, args=(conf_dir_path,))
        p.start()
        return p

    @classmethod
    def start_in_subprocess(cls, conf_dir_path):
        # create a run.py file:

        with tempfile.NamedTemporaryFile(mode='w') as file:
            file.write(
                "from {} import {}".format(cls.__module__, cls.__name__) +
                "\n\nif __name__ == '__main__':"
                "\n    {}.start_component('{}')".format(cls.__name__, conf_dir_path)
            )
            file.seek(0)
            run_subprocess((sys.executable, str(os.path.join(tempfile.tempdir, str(file.name)))))

    # ----------------------------------------------- ABSTRACT ---------------------------------------------------------
    def configure_logging(self):
        """
        Performs logging configuration
        """
        raise NotImplementedError

    @property
    def django_d(self):
        """
        Returns
        -------

        Django configuration
        """
        raise NotImplementedError

    def run(self):
        """
        Must only be called after, configuration and setup.
        """
        raise NotImplementedError
