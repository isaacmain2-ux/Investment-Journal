"""Ensures the project root is on sys.path so tests can `import src...`
regardless of where pytest is invoked from."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
