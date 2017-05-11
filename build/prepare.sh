#!/bin/bash
#
# Usage:
#   ./prepare.sh <function name>

set -o nounset
set -o pipefail
set -o errexit

source build/common.sh

# we're always doing it without threads for now.  not sure about signal module
# just yet.  have to implement "trap"?
configure() {
  cd $PY27
  time ./configure --without-threads
}

# Clang makes this faster.  We have to build all modules so that we can
# dynamically discover them with py-deps.
#
# Takes about 27 seconds on a fast i7 machine.

build-python() {
  cd $PY27
  make clean
  # NOTE: Python passes a few flags, so we can't use CFLAGS here.  Is would
  # have to be EXTRA_CFLAGS?
  time make -j 7 #CFLAGS='-O0'
  #time make -j 7 CFLAGS='-O0'
}

"$@"
