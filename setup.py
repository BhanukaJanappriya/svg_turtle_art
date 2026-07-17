"""Compatibility shim.

The project is configured entirely in ``pyproject.toml``; this exists only so
that legacy tooling invoking ``python setup.py`` still works. Prefer
``pip install .``.
"""

from setuptools import setup

setup()
