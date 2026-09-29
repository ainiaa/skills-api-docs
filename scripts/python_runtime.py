"""Minimum Python version shared by the public command-line entrypoints."""

import sys


MINIMUM_PYTHON = (3, 11)


def require_python(version=None):
    current = sys.version_info if version is None else version
    if tuple(current[:2]) < MINIMUM_PYTHON:
        raise RuntimeError("Python 3.11 or newer is required")
