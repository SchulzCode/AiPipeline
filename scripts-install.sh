#!/usr/bin/env sh
set -eu
python -m pip install -e .
aipipe doctor || true
echo "AIpipe installed. Run 'aipipe --repo /path/to/project doctor' for a target project."
