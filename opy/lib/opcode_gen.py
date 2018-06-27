#!/usr/bin/python
from __future__ import print_function
"""
opcode_gen.py
"""

import sys

from lib import opcode


def log(msg, *args):
  if args:
    msg = msg % args
  print(msg, file=sys.stderr)


def main(argv):
  # Print opcodes in numerical order.  They're not contiguous integers.
  for num in sorted(opcode.opmap.itervalues()):
    # SLICE+1 -> SLICE_1
    name = opcode.opname[num].replace('+', '_')
    print('#define %s %d' % (name, num))

  print('')
  print('#define HAVE_ARGUMENT %d' % opcode.HAVE_ARGUMENT)


if __name__ == '__main__':
  try:
    main(sys.argv)
  except RuntimeError as e:
    print >>sys.stderr, 'FATAL: %s' % e
    sys.exit(1)
