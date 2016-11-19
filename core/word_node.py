#!/usr/bin/env python3
# Copyright 2016 Andy Chu. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#   http://www.apache.org/licenses/LICENSE-2.0
"""
word_node.py -- AST Nodes for the word language.

In contrast to the "dumb" nodes for the arith, bool, and command languages,
these nodes have a lot of behavior defined by virtual dispatch, precisely
BECAUSE the other 3 languages use the words as "tokens".
"""

import io
import re

from core.tokens import *
from core.value import Value
from core import tokens

from core import util

#
# Word
#

# TODO: This should be CType() I think
WordKind = util.Enum('WordKind',
    'UNDEFINED COMMAND OPERATOR REDIR Eof'.split())

EAssignKeyword = util.Enum('EAssignKeyword',
    'NONE DECLARE EXPORT LOCAL READONLY'.split())

# http://stackoverflow.com/questions/4419704/differences-between-declare-typeset-and-local-variable-in-bash
# "local and declare are mostly identical and take all the same arguments with
# two exceptions: local will fail if not used within a function, and local with
# no args filters output to print(only locals, declare doesn't.")
EAssignFlags = util.Enum('EAssignFlags', 'EXPORT READONLY'.split())
# I think I need scope and flags
EAssignScope = util.Enum('EAssignScope', 'LOCAL GLOBAL'.split())

#
# Word types (distinct from token type).
#

# NOTE: There is also an LIT_LBRACE token, for brace expansion.
EKeyword = util.Enum('EKeyword',
""" NONE LBRACE RBRACE
    FOR WHILE UNTIL DO DONE IN 
    CASE ESAC IF FI THEN ELSE ELIF BANG
    LEFT_DBRACKET RIGHT_DBRACKET
    FUNCTION
""".split())

#
# WordPart
#


class WordPart(object):

  def __repr__(self):
    # repr() always prints as a single line
    f = io.StringIO()
    self.PrintLine(f)
    return f.getvalue()

  def PrintTree(self, f):
    raise NotImplementedError

  def PrintLine(self, f):
    # Circular -- each part must override at least one
    f.write(repr(self))

  def TokenPair(self):
    """
    Returns:
      Leftmost token and rightmost token.
    """
    raise NotImplementedError(self.__class__.__name__)

  def Eval(self, ev, quoted=False):
    """Evaluate to a string Value.
    
    For the case where glob is turned off, or we're in DoubleQuotedPart, etc.

    Args:
      ev: _Evaluator
      quoted: Whether we're in a double quoted context

    Returns:
      ok: bool, success
      value: Value, which represents a string or list
    """
    raise NotImplementedError

  def EvalStatic(self):
    """Evaluate a word at PARSE TIME.

    Used for here doc delimiters, function names, and for loop variable names.

    The first step is to follow the normal rules of parsing, but then we
    disallow var sub, command sub, arith sub, etc.

    Returns:
      3-tuple of 
        ok: bool, success
        value: a string (not Value)
        quoted: whether any part of the word was quoted
    """
    raise NotImplementedError

  def UnquotedLiteralValue(self):
    """
    Returns a StringPiece value if it's a literal token, otherwise the empty
    string.
    Used for EKeyword and BType.
    """ 
    return ""

  def IsVarLike(self):
    """Return the var name string, or False."""
    return False

  def TestLiteralForSlash(self):
    """
    Returns:
      -2  : Not a literal part
      -1  : It is a literal, but no slash
       0- : position of the slash that is found

    Used for tilde expansion.
    """
    return -2

  def IsLitToken(self, token_type):
    """Returns whether the part is a literal token.
    """
    return False

  def IsSubst(self):
    """
    Returns:
      Is the part an substitution?  (If called
      This is used:
      
      1) To determine whether result of evaluation of the part should be split
      in a unquoted context.
      2) To determine whether an empty string can be elided.
      3) To do globbing.  If we are NOT in a substitution or literal.
    """
    return False

  def GlobsAreExpanded(self):
    """
    Are globs expanded at the top level?  Yes for LiteralPart, and all the var
    sub parts.

    No for TildeSubPart, and all the quoted parts.
    """
    return False

  def IsArrayLiteral(self):
    """Used for error checking."""
    return False


class ArrayLiteralPart(WordPart):
  """A WordPart that contains other WORDS.

  (In contrast, a DoubleQuotedPart is a WordPart that contains other
  WordParts.)

  It's a WordPart because foo=(a b c) is a word with 2 parts.

  Note that foo=( $(ls /) ) is also valid.

  NOTE: Could this be used for ${foo:-a b c} too?
  """
  def __init__(self):
    WordPart.__init__(self)
    # CommandWord instances.  Can hold CommandSubPart, etc.
    self.words = []

  def __repr__(self):
    return '[Array ' + ' '.join(repr(w) for w in self.words) + ']'

  def Eval(self, ev, quoted=False):
    """ArrayLiteralPart.Eval().

    This is used when we're on the right hand side of an assignment.  Need
    splitting too.

    It can't be quoted... because then it would just be a string.

    """
    return ev.EvalArrayLiteralPart(self)

  def IsArrayLiteral(self):
    return True


class _LiteralPartBase(WordPart):
  def __init__(self, token):
    self.token = token

  def TokenPair(self):
    return self.token, self.token

  def __eq__(self, other):
    return self.token == other.token


class LiteralPart(_LiteralPartBase):
  """A word part written literally in the program text.
  
  It could be unquoted or quoted, depending on if it appears in a
  DoubleQuotedPart.  (SingleQuotedPart contains a list of Token instance, not
  WordPart instances.)
  """
  def __repr__(self):
    # This looks like a token, except it uses [] instead of <>.  We need the
    # exact type to reverse it, e.g. '"' vs \".

    # e.g. for here docs, break it for readability.  TODO: Might want the
    # PrintLine/PrintTree distinction for parts to.
    newline = ''
    #if self.token.val == '\n':
    #  newline = '\n'
    # TODO: maybe if we have the token number, we can leave out the type.  The
    # client can look it up?
    return '[%s %s]%s' % (
        TokenTypeToName(self.token.type), EncodeTokenVal(self.token.val), newline)

  def Eval(self, ev, quoted=False):
    s = self.token.val
    return True, Value.FromString(s)

  def EvalStatic(self):
    return True, self.token.val, False

  def IsVarLike(self):
    if self.token.type == LIT_VAR_LIKE:
      return self.token.val[:-1]  # strip off =
    else:
      return False

  def IsLitToken(self, token_type):
    return self.token.type == token_type

  def TestLiteralForSlash(self):
    return self.token.val.find('/')

  def SplitAtIndex(self, i):
    s = self.token.val
    return s[:i], s[i:]

  def UnquotedLiteralValue(self):
    return self.token.val

  def GlobsAreExpanded(self):
    return True


class EscapedLiteralPart(_LiteralPartBase):
  """Representing \* or \$."""

  def __repr__(self):
    # Quoted part.  TODO: Get rid of \ ?
    return '[\ %s %s]' % (
        TokenTypeToName(self.token.type), EncodeTokenVal(self.token.val))

  def Eval(self, ev, quoted=False):
    val = self.token.val
    assert len(val) == 2, val  # \*
    assert val[0] == '\\'
    s = val[1]
    return True, Value.FromString(s)

  def EvalStatic(self):
    # I guess escaped literal is fine, like \E ?
    return True, self.token.val[1:], True

  # IsVarLike, IsLitToken, TestLiteralForSlash: default values.  SplitAtIndex?
  # Only exists on regular LiteralPart


class SingleQuotedPart(WordPart):

  def __init__(self):
    self.tokens = []  # list of LIT_CHARS tokens

  def TokenPair(self):
    if self.tokens:
      return self.tokens[0], self.tokens[-1]
    else:
      # NOTE: This can't happen with ''.  TODO: Include the actual single
      # quote!
      return None, None

  def __repr__(self):
    return '[SQ %s]' % (' '.join(repr(t) for t in self.tokens))

  def _Eval(self):
    """Shared between Eval and EvalStatic."""
    return ''.join(t.val for t in self.tokens)

  def Eval(self, ev, quoted=False):
    s = self._Eval()
    return True, Value.FromString(s)

  def EvalStatic(self):
    # Single quoted literal can be here delimiter!  Like 'EOF'.
    return True, self._Eval(), True


class DoubleQuotedPart(WordPart):
  def __init__(self):
    # TODO: Add token_type?  LEFT_D_QUOTE, LEFT_DD_QUOTE.  But what about here
    # doc?  It could be a dummy type.
    self.parts = []

  def __eq__(self, other):
    return self.parts == other.parts

  def __repr__(self):
    return '[DQ ' + ''.join(repr(p) for p in self.parts) + ']'

  def TokenPair(self):
    if self.parts:
      begin, _ = self.parts[0].TokenPair()
      _, end = self.parts[-1].TokenPair()
      return begin, end
    else:
      return None, None

  def Eval(self, ev, quoted=False):
    """DoubleQuotedPart.Eval()

    NOTE: This is very much like CommandWord.Eval(), except that we don't need
    to split with IFS, and we don't elide empty values.
    """
    return ev.EvalDoubleQuotedPart(self)

  def EvalStatic(self):
    ret = ''
    for p in self.parts:
      ok, s, _ = p.EvalStatic()
      if not ok:
        return False, '', True
      ret += s

    return True, ret, True  # At least one part was quoted!


class CommandSubPart(WordPart):
  def __init__(self, token, command_list):
    self.token = token
    self.command_list = command_list

  def __eq__(self, other):
    return self.command_list == other.command_list

  def __repr__(self):
    f = io.StringIO()
    self.command_list.PrintLine(f)  # print(on a single line)
    return '[ComSub %s]' % f.getvalue()

  def Eval(self, ev, quoted=False):
    # TODO: If token is LEFT_PROC_SUB_IN or LEFT_PROC_SUB_OUT, we have to
    # supply something like /dev/fd/63.
    return ev.EvalCommandSub(self.command_list)

  def EvalStatic(self):
    return False, '', False

  def IsSubst(self):
    return True

  def GlobsAreExpanded(self):
    return True


class VarSubPart(WordPart):

  def __init__(self, name, token=None):
    """
    Args:
      name: a string, including '@' '*' '#' etc.?
      token: For debugging only?
    """
    self.name = name
    self.token = token

    # TODO: seprate array_op -- better for oil
    self.bracket_op = None  # either IndexVarOp or ArrayVarOp
    self.test_op = None  # TestVarOp -- one of 8 types
    self.transform_ops = []  # list of length/strip/slice/patsub 

  def PrintLine(self, f):
    f.write('[VarSub %s' % self.name)  # no quotes around name
    if self.bracket_op:
      f.write(' bracket_op=%r' % self.bracket_op)
    if self.test_op:
      f.write(' test_op=%r' % self.test_op)
    if self.transform_ops:
      f.write(' transform_ops=%r' % self.transform_ops)
    f.write(']')

  def TokenPair(self):
    if self.token:
      return self.token, self.token
    else:
      return None, None

  def Eval(self, ev, quoted=False):
    return ev.EvalVarSub(self, quoted=quoted)

  def EvalStatic(self):
    return False, '', False

  def IsSubst(self):
    return True

  def GlobsAreExpanded(self):
    return True


class TildeSubPart(WordPart):
  # NOTE: NOT IsSubst

  def __init__(self, prefix):
    """
    Args:
      prefix: tilde prefix ("" if no prefix)
    """
    self.prefix  = prefix

  def __repr__(self):
    return '[TildeSub %r]' % self.prefix

  def Eval(self, ev, quoted=False):
    # We never parse a quoted string into a TildeSubPart.
    assert not quoted 
    return ev.EvalTildeSub(self.prefix)

  def EvalStatic(self):
    print('~ is not allowed')
    return False, '', False


class ArithSubPart(WordPart):

  def __init__(self, anode):
    self.anode = anode

  def __repr__(self):
    return '[ArithSub %r]' % self.anode

  def Eval(self, ev, quoted=False):
    return ev.EvalArithSub(self.anode)

  def EvalStatic(self):
    print('$(()) is not allowed)')
    return False, '', False

  def IsSubst(self):
    return True


class _ATokenInterface(object):
  """
  Common interface between simple tokens like 99 and +, as well as words like
  Foo+
  """
  def AType(self):
    """Distinguish between words and operators for parsing.

    ( ) is necessary

    operator is necessary. 

    TODO: Also precedence if it's an operator.  I think I should return that
    here.

    Like BOOLEAN_OP_TABLE, have ARITH_OP_TABLE.
    """
    raise NotImplementedError


class _BTokenInterface(object):
  """
  Common interface between unevaluated words (for [[ ) and evaluated words
  (for [ ).
  """
  def BType(self):
    """Return a token type for [[ and [."""
    raise NotImplementedError


class BToken(object):
  """Concrete class For [.

  Differences: uses -a and -o.  No ( ).

  Problem: In C++, you will have to use the parser at RUNTIME.  So it might
  have to be rewritten anyway.
  """
  def __init__(self, arg):
    self.arg = arg

  def BType(self):
    """Return a token type."""


#
# Word
#


class Word(_ATokenInterface, _BTokenInterface):

  def __init__(self):
    pass

  def __repr__(self):
    # repr() always prints as a single line
    f = io.StringIO()
    self.PrintLine(f)
    return f.getvalue()

  def PrintTree(self, f):
    raise NotImplementedError

  def PrintLine(self, f):
    raise NotImplementedError

  def TokenPair(self):
    """
    Returns:
      Leftmost token and rightmost token.
    """
    raise NotImplementedError

  def Type(self):
    """Return the TokenType (TokenWord), or EKeyword enum (CommandWord).

    TODO: Should we separate these two concepts?  TokenType() and Keyword()?
    """
    raise NotImplementedError

  def Kind(self):
    """Return WordKind (COMMAND OPERATOR Eof)"""
    raise NotImplementedError


class CommandWord(Word):
  """For now this can just hold a double quoted token."""
  def __init__(self, parts=None):
    Word.__init__(self)
    self.parts = parts or []  # public, mutable
    self.word_type = -1  # -1: uninitialized

  def __eq__(self, other):
    return self.parts == other.parts

  def PrintLine(self, f):
    # TODO: Consider indenting parts if they are complex, like a command sub
    # part.

    # NOTE: Is the K needed?  It's nice for human readability, but programs
    # might not need it.

    suffix = ' =' if self.LooksLikeAssignment() else ''
    s = '{' + ' '.join(repr(p) for p in self.parts) + ('%s}' % suffix)
    f.write(s)

  def TokenPair(self):
    if self.parts:
      begin_token, _ = self.parts[0].TokenPair()
      _, end_token = self.parts[-1].TokenPair()
      return begin_token, end_token
    else:
      return None, None

  def Kind(self):
    return WordKind.COMMAND

  # TODO:
  # - Put all the keywords under LIT, and then if there is exactly one part,
  # test against the token type of LIT_FOR, LIT_LEFT_DBRACKET, etc.
  # - Do you still need caching?  I guess it could be tested over and over
  # again.
  # - Rename to CType() or CmdType()?
  def Type(self):
    """Returns an EKeyword enum."""
    if self.word_type == -1:  # not computed yet

      # has to be a single literal part
      if len(self.parts) != 1:
        self.word_type = EKeyword.NONE
        return self.word_type

      lit = self.parts[0].UnquotedLiteralValue()
      if lit == "{":
        self.word_type = EKeyword.LBRACE
      elif lit == "}":
        self.word_type = EKeyword.RBRACE
      elif lit == "for":
        self.word_type = EKeyword.FOR
      elif lit == "case":
        self.word_type = EKeyword.CASE
      elif lit == "if":
        self.word_type = EKeyword.IF
      elif lit == "fi":
        self.word_type = EKeyword.FI
      elif lit == "then":
        self.word_type = EKeyword.THEN
      elif lit == "elif":
        self.word_type = EKeyword.ELIF
      elif lit == "else":
        self.word_type = EKeyword.ELSE
      elif lit == "while":
        self.word_type = EKeyword.WHILE
      elif lit == "until":
        self.word_type = EKeyword.UNTIL
      elif lit == "do":
        self.word_type = EKeyword.DO
      elif lit == "done":
        self.word_type = EKeyword.DONE
      elif lit == "in":
        self.word_type = EKeyword.IN
      elif lit == "esac":
        self.word_type = EKeyword.ESAC
      elif lit == "!":
        self.word_type = EKeyword.BANG
      elif lit == "function":
        self.word_type = EKeyword.FUNCTION
      elif lit == "[[":
        self.word_type = EKeyword.LEFT_DBRACKET
      elif lit == "]]":
        self.word_type = EKeyword.RIGHT_DBRACKET

      else:
        self.word_type = EKeyword.NONE

    return self.word_type

  def AType(self):
    return NODE_ARITH_WORD

  def BType(self):
    if len(self.parts) != 1:
      return BType.ATOM_TOK

    lit = self.parts[0].UnquotedLiteralValue()
    #print("LIT", lit, self.word)

    for char in tokens.UNARY_FILE_CHARS:
      if lit == ('-' + char):
        name = 'UNARY_FILE_' + char
        return getattr(BType, name)

    if lit == ']]':
      return BType.Eof_TOK

    if lit == '!':
      return BType.LOGICAL_UNARY_NOT

    if lit == '-ef':
      return BType.BINARY_FILE_EF
    if lit == '-nt':
      return BType.BINARY_FILE_NT
    if lit == '-ot':
      return BType.BINARY_FILE_OT

    if lit == '-eq':
      return BType.BINARY_INT_EQ
    if lit == '-ne':
      return BType.BINARY_INT_NE

    if lit == '-gt':
      return BType.BINARY_INT_GT
    if lit == '-ge':
      return BType.BINARY_INT_GE
    if lit == '-lt':
      return BType.BINARY_INT_LT
    if lit == '-le':
      return BType.BINARY_INT_LE

    if lit == '=':
      return BType.BINARY_STRING_EQUAL
    if lit == '==':
      return BType.BINARY_STRING_EQUAL
    if lit == '!=':
      return BType.BINARY_STRING_NOT_EQUAL
    if lit == '=~':
      return BType.BINARY_STRING_TILDE_EQUAL

    if lit == '-z':
      return BType.UNARY_STRING_z
    if lit == '-n':
      return BType.UNARY_STRING_n

    if lit == '-o':
      return BType.UNARY_OTHER_o
    if lit == '-v':
      return BType.UNARY_OTHER_v
    if lit == '-R':
      return BType.UNARY_OTHER_R

    # If nothing else matches, it's an atom
    return BType.ATOM_TOK

  def EvalStatic(self):
    """
    Returns a string, and whether any part was quoted.
    """
    ret = ''
    quoted = False
    for p in self.parts:
      ok, s, q = p.EvalStatic()
      if not ok:
        return False,'', quoted
      if q:
        quoted = True
      ret += s
    return True, ret, quoted

  def HasArrayPart(self):
    for part in self.parts:
      if part.IsArrayLiteral():
        return True
    return False

  # TODO for optimization: Put all the keywords under LIT, and then if there is
  # exactly one part, test against the token type of LIT_FOR,
  # LIT_LEFT_DBRACKET, etc.
  def ResolveAssignmentBuiltin(self):
    """Tests if word is an assignment builtin."""
    # has to be a single literal part
    if len(self.parts) != 1:
      return EAssignKeyword.NONE

    lit = self.parts[0].UnquotedLiteralValue()
    if lit == "declare":
      return EAssignKeyword.DECLARE
    if lit == "export":
      return EAssignKeyword.EXPORT
    if lit == "local":
      return EAssignKeyword.LOCAL
    if lit == "readonly":
      return EAssignKeyword.READONLY

    return EAssignKeyword.NONE

  def LooksLikeAssignment(self):
    if len(self.parts) == 0:
      return False
    name = self.parts[0].IsVarLike()
    rhs = CommandWord()
    if name:
      if len(self.parts) == 1:
        # NOTE: This is necesssary so that EmptyUnquoted elision isn't
        # applied.  EMPTY= is like EMPTY=''.
        rhs.parts.append(SingleQuotedPart())
      else:
        for p in self.parts[1:]:
          rhs.parts.append(p)
      return name, rhs
    return False

  def AsFuncName(self):
    ok, s, quoted = self.EvalStatic()
    if not ok:
      return False, ''
    if quoted:
      if len(self.parts) != 1:
        raise RuntimeError(
            "Function names should not have quotes, got: %s", self.parts)
    return True, s

  def BraceExpand(self):
    """
    Returns:
      A list of new Word instances, or None if there was no brace expansion
      detected.
    """
    # Algorithm:
    # 
    # Look for patterns like LBRACE COMMA RBRACE
    # And then form cross product somehow.

    # "A correctly-formed brace expansion must contain unquoted opening and
    # closing braces, and at least one unquoted comma or a valid sequence
    # expression.  Any incorrectly formed brace expansion is left unchanged. "

    # Could this be recursive?  preamble,options,postscript
    #
    # Hm bash also has integer expressions!  {1..3} => {1,2,3}
    # {1..5..2} => {1,3,5}
    # - mksh doesn't have it.

    # look for subseqeuence like '{' ','+ '}'
    # And then make a data structure for this.


class TokenWord(Word):
  """A word that is just a token.

  NOTES:
  - The token range for this token may be more than one.  For example: a
    OP_NEWLINE is a token word that the CommandParser needs to know about.  It
    may "own" IGNORED_COMMENT and IGNORED_SPACE nodes preceding it.  These are
    tokens the CommandParser does NOT need to know about.
  - the Eof_REAL TokenWord owns and trailing whitespace.
  """
  def __init__(self, token):
    Word.__init__(self)
    self.token = token

  def __eq__(self, other):
    return self.token == other.token

  def PrintLine(self, f):
    f.write('{%s %s}' % (
        TokenTypeToName(self.token.type), EncodeTokenVal(self.token.val)))

  def TokenPair(self):
    return self.token, self.token

  def Kind(self):
    token_kind = self.token.Kind() 
    if token_kind == TokenKind.Eof:
      return WordKind.Eof
    elif token_kind == TokenKind.REDIR:
      return WordKind.REDIR
    else:
      return WordKind.OPERATOR

  def Type(self):
    return self.token.type

  def AType(self):
    # $(( 1+2 ))
    # (( a=1+2 ))
    # ${a[ 1+2 ]}
    # ${a : 1+2 : 1+2}
    #if self.token.type in (RIGHT_ARITH_SUB, VS_OP_RBRACKET, VS_OP_COLON):
    #  return Eof_ARITH
    return self.token.type  # e.g. AS_PLUS

  def BType(self):
    ty = self.token.type
    if ty == OP_AND_IF:
      return BType.LOGICAL_BINARY_AND
    if ty == OP_OR_IF:
      return BType.LOGICAL_BINARY_OR

    if ty == REDIR_LESS:  # <
      return BType.BINARY_STRING_LESS
    if ty == REDIR_GREAT:  # <
      return BType.BINARY_STRING_GREAT

    if ty == OP_LPAREN:
      return BType.PAREN_LEFT
    if ty == OP_RPAREN:
      return BType.PAREN_RIGHT

    if ty == OP_NEWLINE:
      return BType.NEWLINE_TOK

    raise AssertionError(self.token)
    # Are invalid operators like << OK?  Bash doesn't allow them.
    return BType.ATOM_TOK


class _VarOp(object):
  """Base class for operations."""
  def __init__(self, vtype):
    self.vtype = vtype  # type: TOKEN
                        # I think tokens are better.  
                        # INDEX should be [ - VS_OP_LBRACKET
                        # ARRAY should be @ / * - VS_AT or AS_STAR ?
                        # LENGTH should be # - VS_POUND
                        #
                        # unary # - VS_UNARY_POUND, etc.
                        # SLICE: VS_OP_COLON 
                        # PATSUB: VS_OP_SLASH

  def PrintLine(self, f):
    raise NotImplementedError

  # TODO: Unify with AstNode
  def __repr__(self):
    f = io.StringIO()
    self.PrintLine(f)
    return f.getvalue()


class IndexVarOp(_VarOp):
  """ $a[i+1] """
  def __init__(self, index_expr):
    _VarOp.__init__(self, VS_OP_LBRACKET)
    self.index_expr = index_expr  # type: _ANode

  def PrintLine(self, f):
    f.write('(Index %s)' % self.index_expr)


class ArrayVarOp(_VarOp):
  """ ${a[@]} or ${a[*]} 

  Take all the elements of an array, to remove ambiguity.

  vtype = VType.AT or VType.STAR
  """
  def PrintLine(self, f):
    f.write('(Array %s)' % TokenTypeToName(self.vtype))


class LengthVarOp(_VarOp):
  """ ${#a}  and ${#a[@]}
  """
  def __init__(self):
    _VarOp.__init__(self, VS_POUND)

  def PrintLine(self, f):
    f.write('(#len)')


class RefVarOp(_VarOp):
  """ ${!s}  and ${!s[0]}, but NOT ${!s[@]}
  """
  def __init__(self):
    _VarOp.__init__(self, VS_BANG)

  def PrintLine(self, f):
    f.write('(!ref)')


class TestVarOp(_VarOp):
  """ ${a:-default} and friends """
  def __init__(self, vtype, arg_word):
    _VarOp.__init__(self, vtype)
    self.arg_word = arg_word  # type: CommandWord

  def PrintLine(self, f):
    f.write('%s %s' % (TokenTypeToName(self.vtype), self.arg_word))


class StripVarOp(_VarOp):
  """ ${a%suffix} and friends """
  def __init__(self, vtype, arg_word):
    _VarOp.__init__(self, vtype)
    self.arg_word = arg_word  # type: CommandWord
    # If there are n words, then there are n-1 space tokens in between them

  def PrintLine(self, f):
    f.write('%s %s' % (TokenTypeToName(self.vtype), self.arg_word))


class SliceVarOp(_VarOp):
  """ ${a : i+1 : 3}  or  ${a[@] : i+1 : 3} or ${a : 0}"""
  def __init__(self, begin, length):
    _VarOp.__init__(self, VS_OP_COLON)
    self.begin = begin  # type: _ANode
    # None means slice until end
    self.length = length  # Optional[_ANode]

  def PrintLine(self, f):
    f.write('Slice %s %s' % (self.begin, self.length))


class PatSubVarOp(_VarOp):
  """ ${a/foo*/foo} """
  def __init__(self, pat, replace, do_all, do_prefix, do_suffix):
    _VarOp.__init__(self, VS_OP_SLASH)
    # Can be a glob pattern
    self.pat = pat  # type: CommandWord
    self.replace = replace  # type: Optional[CommandWord]

    self.do_all = do_all # ${v//foo/bar}
    self.do_prefix = do_prefix  # ${v/%foo/bar}
    self.do_suffix = do_suffix  # ${v/#foo/bar}

  def PrintLine(self, f):
    f.write('PatSub %r %r' % (self.pat, self.replace))

    if self.do_all:
      f.write(' do_all')
    if self.do_prefix:
      f.write(' do_prefix')
    if self.do_suffix:
      f.write(' do_suffix')