import unittest
import tempfile
import os

from oservices import ConfigurationManager, ConfField, Component


class _PackageConfManager(ConfigurationManager):
    name = ConfField(value="p")


package_conf_manager = _PackageConfManager("package", "package_conf")
package_conf = package_conf_manager.to_conf()


class _ServiceConfManager(ConfigurationManager):
    a = ConfField(value="a")

service_conf_manager = _ServiceConfManager("service", "service_conf")
service_conf = service_conf_manager.to_conf()


class _ComponentConfManager(ConfigurationManager):
    b = ConfField("b")

component_conf_manager = _ComponentConfManager("component", "component_conf")
component_conf = component_conf_manager.to_conf()

COMPONENT = Component("service_name", "name", (component_conf, package_conf, service_conf))


class ComponentTest(unittest.TestCase):
    def test_generate_confs(self):
        with tempfile.TemporaryDirectory() as dir_path:
            conf_dir_path = COMPONENT.standard_configure(dir_path)
            self.assertIn(COMPONENT._INFO, os.listdir(conf_dir_path))
