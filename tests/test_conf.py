import unittest
import tempfile
import os

from oservices import ConfigurationManager
from .conf_util import simple_conf, simple_conf_manager, with_hd_conf_manager, with_hd_conf


class ConfTest(unittest.TestCase):
    def test_simple(self):
        with tempfile.TemporaryDirectory() as dir_path:
            simple_conf.standard_configure(dir_path, "service", "component")
            conf_path = simple_conf.build(dir_path, "service", "component")
            # check conf path
            self.assertEqual(os.path.join(dir_path, "conf", "service-component",
                                          "outil.services.tests.conf_util.simple_conf"),
                             conf_path)

            # load conf
            _conf = ConfigurationManager.set_conf_from_file(conf_path)

            # check both confs are equal
            expected = dict(int=1, str="str")
            self.assertEqual(expected, _conf.to_dict())
            self.assertEqual(expected, simple_conf_manager.to_dict()["conf"])

    def test_hd_elements(self):
        with tempfile.TemporaryDirectory() as dir_path:
            with_hd_conf.standard_configure(dir_path, "service", "component")
            conf_path = with_hd_conf.build(dir_path, "service", "component")
            # check conf path
            self.assertEqual(
                os.path.join(
                    dir_path,
                    "conf",
                    "service-component",
                    "outil.services.tests.conf_util.with_hd_conf"),
                conf_path)

            # load conf
            _conf = ConfigurationManager.set_conf_from_file(conf_path)

            # check conf is ok
            expected = dict(
                    int=1,
                    str="str",
                    log_file_path=os.path.join(dir_path, "logging", "service-component-main.log"),
                    db_dir_path=os.path.join(dir_path, "data", "service-component-adb"),
                    sqlite_db=dict(
                        ENGINE='django.db.backends.sqlite3',
                        NAME=os.path.join(dir_path, "data", "service-component-db.sqlite3")
                    )
            )
            self.assertEqual(
                expected,
                _conf.to_dict(),
                _conf.to_dict()
            )
