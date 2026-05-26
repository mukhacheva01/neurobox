"""Pytest config and fixtures for НейроБокс."""
import os
import sys

# Корень проекта в path
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Загрузка .env из корня
_env = os.path.join(_root, ".env")
if os.path.isfile(_env):
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)

os.chdir(_root)

# Минимальные заглушки для полей без default, чтобы Settings() не падал при pytest
_test_defaults = {
    "BOT_TOKEN": "0:test_token_for_pytest",
}
for _k, _v in _test_defaults.items():
    os.environ.setdefault(_k, _v)
