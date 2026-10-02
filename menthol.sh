#!/bin/bash
cd "$(dirname "$0")"
./venv/bin/python -m src.main "$@"
