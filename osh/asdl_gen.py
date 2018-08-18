#!/usr/bin/env python
from __future__ import print_function
"""
ast_gen.py: Generate the Id enum in C code.

# TODO: This should be renamed to asdl_gen.py
"""

import os
import pickle
import sys

from asdl import asdl_ as asdl
from asdl import front_end
from asdl import gen_cpp
from asdl import gen_python

def main(argv):
  try:
    action = argv[1]
  except IndexError:
    raise RuntimeError('Action required')

  try:
    schema_path = argv[2]
  except IndexError:
    raise RuntimeError('Schema path required')

  if os.path.basename(schema_path) == 'types.asdl':
    app_types = {}
  else:
    from osh.meta import Id
    app_types = {'id': asdl.UserType(Id)}

  if action == 'c':  # Generate C code for the lexer
    with open(schema_path) as f:
      asdl_module, _ = front_end.LoadSchema(f, app_types)

    v = gen_cpp.CEnumVisitor(sys.stdout)
    v.VisitModule(asdl_module)

  elif action == 'py':  # Generate Python code so we don't depend on ASDL schemas
    type_lookup_import = argv[3]
    try:
      pickle_out_path = argv[4]
    except IndexError:
      pickle_out_path = None
    pickle_out_path = None

    p = front_end.ASDLParser()
    with open(schema_path) as input_f:
      module = p.parse(input_f)

    f = sys.stdout

    f.write("""\
from asdl import const  # For const.NO_INTEGER
from asdl import py_meta
%s

""" % type_lookup_import)

    v = gen_python.GenClassesVisitor(f)
    v.VisitModule(module)

    if pickle_out_path:
      import pickle
      from osh.meta import Id
      app_types = {'id': asdl.UserType(Id)}
      with open(schema_path) as input_f:
        module, type_lookup = front_end.LoadSchema(input_f, app_types)

      with open(pickle_out_path, 'w') as f:
        pickle.dump(type_lookup.runtime_type_lookup, f, protocol=2)
      from core.util import log
      log('Wrote %s', pickle_out_path)


    # TODO: Also generate reflection data.  Should it be a tiny stack bytecode
    # with BUILD_CLASS and setattr() ?  Hm.  Maybe do it like Pickle.
    # Or honestly oheap can express a graph.  But it has a different API.  You
    # can write a Python API for it, but it would need a code generator.

    # Easier solution: _RuntimeType has a 'seen' bit that starts out false.
    # Then
    # We want to serialize a dict of {string: _RuntimeType}, but it also has
    # internal fields that are lists of tuples, and the tuples point to more
    # instances.
    # Maybe write an unpickler in Python that only supports the opcodes we need?

    # There are 13 instructions plus STOP!  Yeah this is a fun little problem.
    # It's a data serialization VM.
    # Unpickler is squite small.

    # Uh it uses s.decode('string-escape')?
    # why not BINSTRING?
    #
    # Oh that's version 2.
    # In version 2, now I have 16 opcodes + STOP.

  else:
    raise RuntimeError('Invalid action %r' % action)


if __name__ == '__main__':
  try:
    main(sys.argv)
  except RuntimeError as e:
    print('FATAL: %s' % e, file=sys.stderr)
    sys.exit(1)
