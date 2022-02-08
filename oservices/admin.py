import argparse
import inspect
import sys


from .settings import SettingsManager, SettingsField
from .processes import register_exit
# fixme: see if backup is still relevant (if not, remove). See work/backup.
# from .backup import restore

class AdminError(Exception):
    pass


class CommandArg:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class Command:
    command = "command"
    Arg = CommandArg

    def __init__(self, *arguments, concerned_components=None, help=None):
        self.arguments = arguments
        self.concerned_components = concerned_components
        self.help = help

    def __call__(self, method):
        setattr(method, self.command, self)
        return method


class CommandFct:
    def __init__(
            self,
            command_name,
            available_components_d,
            app_data_dir_path,
            administrator,
            cmd_method
                 ):
        self.command_name = command_name
        self.available_components_d = available_components_d
        self.app_data_dir_path = app_data_dir_path
        self.administrator = administrator
        self.cmd_method = cmd_method

    def __call__(self, parsed_args, unknown_args):
        """
        Parameters
        ----------
        parsed_args: arparse parsed_args (see documentation)
        unknown_args: arparse unknown_args (see documentation)

        Returns
        -------
        * propagates settings
        * standard configures (without build)
        * registers exit
        * calls command
        """
        # todo: precisely document what is done here

        service_name = parsed_args.service
        component_name = parsed_args.component

        # check component is known
        assert (service_name, component_name) in self.available_components_d, \
            "%s command is not registered for %s|%s. Available components:\n%s" % (
                self.command_name,
                service_name,
                component_name,
                ["* %s:%s\n" % (s_name, c_name) for (s_name, c_name) in sorted(self.available_components_d)])
        component = self.available_components_d[(service_name, component_name)]

        # propagate settings
        self.administrator.propagate_settings(component, parsed_args.carg)

        # standard configure (without build)
        component.standard_configure(self.app_data_dir_path, build=False)

        # register exit
        register_exit(is_main_process=True)

        # call method
        return self.cmd_method(component, parsed_args, unknown_args)


class Administrator(SettingsManager):
    """
    Reserved names for settings variables : private '_*', 'settings', 'propagate_settings', 'cmd_*'

    To create a new command:
        * create a method named cmd_{cmd_name} (decorating it is not necessary), with following signature:
            self, component, parsed_args, unknown_args
        * to customize argument and behaviour: use Command decorator, and declare arguments with CommandArg

    Steps that have already been performed before running command:
        * settings have been loaded and propagated
        * configurations have been configured (without build)
        * exit has been registered
    """
    APP_DATA_DIR_PATH = SettingsField()
    BACKUP = SettingsField(optional=True)
    # {
    # host:
    # login:
    # password:
    # prefix:
    # root_temp_dir:
    #
    # tarball: {
    #     refs: {ref: base_dir, ...}  dict of dirs to download
    #     ref: backup-manager: "backup_prefix-{ref}.YYYYMMJJ.master.tar.gz",
    #     base_dir: root directory of tarball to extract (ex: data/openergy/ohive/ftp/data
    # }
    #
    # pgsql: {
    #     refs: list of pg databases
    #     host: (optional) 'localhost',
    #     port: (optional) '5432'
    #     user:
    #     password:
    #     admin: (optional - default user)  # will create db after drop
    #     admin_password: (optional - default user)
    # }

    def __init__(self, name, components, settings_module_name="settings"):
        super().__init__(settings_module_name=settings_module_name)

        self._components_d = dict([((c.service_name, c.name), c) for c in components])
        self._parser = argparse.ArgumentParser(name)

        if self._settings_where_loaded:
            # load commands
            self._load_commands()

    def _load_commands(self):
        # add default arguments to parser
        services = set(c[0] for c in self._components_d)
        self._parser.add_argument(
            "service",
            choices=services,
            help="Available services: %s" % ", ".join(sorted(services))
        )
        components = set(c[1] for c in self._components_d)
        self._parser.add_argument(
            "component",
            choices=components,
            help="Available components: %s" % ", ".join(sorted("(%s:)%s"% k for k in self._components_d))
        )
        self._parser.add_argument("-c", "--carg", help="component argument: depends on chosen component")

        # prepare sub-parser mode
        _sub_parser = self._parser.add_subparsers(dest="sub_command")
        _sub_parser.required = True  # could be removed in the future if we want to propose direct commands

        # create parser
        for k in dir(self):
            # skip private variables
            if k[:1] == "_":
                continue

            # only use commands
            if k[:4] != "cmd_":
                continue

            # skip variables
            v = getattr(self, k)
            if not inspect.ismethod(v):
                continue

            # create customizer if needed
            if hasattr(v, Command.command):
                command = getattr(v, Command.command)
                assert isinstance(command, Command), "unknown customized command type"
            else:
                command = Command()

            # check concerned_components are registered
            if command.concerned_components is not None:
                for c in command.concerned_components:
                    assert c in self._components_d.values(), \
                        "Shouldn't be here: mismatch between known components and concerned_components"

            # create parser
            command_name = v.__name__[4:]
            parser = _sub_parser.add_parser(command_name, help=command.help)

            # add custom arguments
            for argument in command.arguments:
                parser.add_argument(*argument.args, **argument.kwargs)

            # prepare available components
            available_components_d = (self._components_d if command.concerned_components is None else
                                      dict([((c.service_name, c.name), c) for c in command.concerned_components]))

            # create command function
            cmd_fct = CommandFct(
                command_name,
                available_components_d,
                self.settings.APP_DATA_DIR_PATH,
                self,
                v)

            # attach it to parser
            parser.set_defaults(func=cmd_fct)

    def __call__(self, *cmd_args):
        if not self._settings_where_loaded:
            raise AdminError("settings files must be provided (import 'settings' must work)")
        args, unknown_args = self._parser.parse_known_args(args=cmd_args)
        args.func(args, unknown_args)

    @Command(
        CommandArg("-s", "--static", action="store_true", help="initialize django static files (default: false)"),
        CommandArg("-m", "--migrate", action="store_true", help="migrate django databases (default: false)"),
        help="start: default behaviour is to build before starting. django migrations will be run. ",
    )
    def cmd_start(self, component, parsed_args, unknown_args):
        """
        Build on required component is automatically performed (to ensure RAM conf is coherent with files conf)
        post_build_hook is for subclassing: def post_build_hook(component, parsed_args, unknown_args)
        """
        sys.stdout.write("Starting %s:%s\n" % (component.service_name, component.name))
        conf_dir_path = component.standard_conf_dir_path(self.settings.APP_DATA_DIR_PATH)

        # build
        sys.stdout.write(" * building conf")
        sys.stdout.flush()
        self.build(component, parsed_args, unknown_args)
        sys.stdout.write("\r * building conf -> ok\n")

        # set conf_dir_path, it may be required, for example to initialize the adb pool processes
        component.conf_dir_path = conf_dir_path

        # setup
        sys.stdout.write(" * setting up")
        sys.stdout.flush()
        self.setup(component, parsed_args, unknown_args)
        sys.stdout.write("\r * setting up -> ok\n")

        # initialize django files
        if component.django_d is not None:
            with_db = parsed_args.migrate
            with_static = parsed_args.static
            if with_db or with_static:
                sys.stdout.write(" * initializing django files")
                sys.stdout.flush()
                component.initialize_django_files(with_db=with_db, with_static=with_static)
                sys.stdout.write("\r * initializing django files -> ok\n")

        # start
        sys.stdout.write(" %s\n" % self.get_start_message(component, parsed_args, unknown_args))
        sys.stdout.flush()
        component.start()

    @Command(
        help="build: prepare app_data directory and create configuration files"
    )
    def cmd_build(self, component, parsed_args, unknown_args):
        self.build(component, parsed_args, unknown_args)

    def build(self, component, parsed_args, unknown_args):
        """
        for subclassing
        """
        component.build(self.settings.APP_DATA_DIR_PATH)

    @Command(
        help="collect_static: collect static files"
    )
    def cmd_collect_static(self, component, parsed_args, unknown_args):
        if component.django_d is None:  # non django app
            return

        # setup
        component.setup()

        # check if static files
        from django.conf import settings

        if getattr(settings, "STATIC_ROOT") is None:  # not static files
            return

        # collect static
        sys.stdout.write(" * collecting django files")
        sys.stdout.flush()
        component.initialize_django_files(with_db=False, with_static=True)
        sys.stdout.write("\r * collecting django files -> ok\n")

    def setup(self, component, parsed_args, unknown_args):
        """
        for subclassing
        """
        component.setup()

    def get_start_message(self, component, parsed_args, unknown_args):
        """
        for subclassing
        """
        return "starting"

    def cmd_django(self, component, parsed_args, unknown_args):
        """
        we don't build
        """
        # setup
        component.setup()
        # load django and execute command
        from django.core.management import execute_from_command_line
        execute_from_command_line([""] + unknown_args)

    # @Command(
    #     CommandArg("-d", "--download_only", action="store_true", help="download only"),
    #     CommandArg("-z", "--unzip_only", action="store_true", help="unzip only"),
    #     CommandArg("-l", "--load_only", action="store_true", help="load only"),
    #     help="downloads backup files, clears current files and restores backup files"
    # )
    # def cmd_restore(self, component, parsed_args, unknown_args):
    #     """
    #     downloads, unzips and loads data
    #     """
    #     restore(component, parsed_args, self.settings)
