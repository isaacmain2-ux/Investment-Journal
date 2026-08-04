"""Tests for src/common/cli.clean_argv - tolerating pasted shell comments."""
import argparse
from src.common.cli import clean_argv


def test_strips_comment_token_and_rest():
    assert clean_argv(["#", "60", "macro", "series"]) == []
    assert clean_argv(["--only", "DGS10", "#", "smoke"]) == ["--only", "DGS10"]
    assert clean_argv(["#comment"]) == []


def test_leaves_clean_args_untouched():
    assert clean_argv(["--only", "DGS10,CPIAUCSL"]) == ["--only", "DGS10,CPIAUCSL"]
    assert clean_argv([]) == []


def test_parser_no_longer_errors_on_comment():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    # would previously raise SystemExit(2) "unrecognized arguments"
    args = ap.parse_args(clean_argv(["#", "60", "macro", "series"]))
    assert args.only is None
    args2 = ap.parse_args(clean_argv(["--only", "DGS10", "#", "note"]))
    assert args2.only == "DGS10"
