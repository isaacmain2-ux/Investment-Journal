"""pytest configuration for the Investment Journal project.

Ensures the project root is on sys.path before any tests are collected, so tests
can import both the `src` package AND root-level modules like `run_cot`. pytest
loads this file automatically; no imports of it are needed.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
