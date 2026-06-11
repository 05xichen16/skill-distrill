"""Offline scoring / regression harness for the contest results.

This package reimplements the platform's grading semantics (calibrated against
the public answer key) so any ``results.json`` can be scored locally without the
remote judge. See ``score.py`` for the type semantics and ``regression.py`` for
the free-score guard rails.
"""
