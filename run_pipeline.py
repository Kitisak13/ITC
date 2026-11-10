#!/usr/bin/env python3
"""Entry point: ``python run_pipeline.py <command>`` (see ``--help``)."""

import sys

from comtrade_pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
