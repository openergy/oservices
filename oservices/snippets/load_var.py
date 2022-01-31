"""
opysnippets/load_var:1.0.0
"""
import importlib


def load_var(var_fullname):
    var_l = var_fullname.split(".")
    mod = importlib.import_module(".".join(var_l[:-1]))
    return getattr(mod, var_l[-1])
