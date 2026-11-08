#!/bin/sh
# Also support the standalone archived scorers in a fresh source checkout.
set -eu
if ! test -x build/check-receipts; then make -s build/check-receipts >&2; fi
exec build/check-receipts "$@"
