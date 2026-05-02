"""Canned analyses over relay log dumps from extract_log.py.

Each script in this directory takes a JSON dump produced by
extract_log.py and answers a specific question about the run:

    cost_by_story.py      — agent dollars spent per story
    failure_patterns.py   — fix_ci cycle counts, common error signatures
    phase_durations.py    — wall-clock time per pipeline phase
    auth_halt_check.py    — confirm auth-halt detection fired (or didn't)

All four are self-contained — pass a dump file path, get a report on stdout.
"""
