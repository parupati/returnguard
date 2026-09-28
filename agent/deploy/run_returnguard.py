"""Databricks Job task file. Uploaded next to the `returnguard` package by scripts/deploy_databricks.py."""

import sys

from returnguard.jobs import main

exit_code = main()
if exit_code:
    sys.exit(exit_code)
