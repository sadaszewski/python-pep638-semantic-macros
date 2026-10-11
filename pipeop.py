"""A pipe operator for Python, as a PEP 638 statement macro.

    from! pipeop import pipe

    pipe!:
        range(16) | map(lambda i: random.randint(97, 122) | chr) | ''.join() | print()

Inside a ``pipe!`` block (or the one-line form ``pipe! a | f | g``) the
``|`` operator passes the value on its left to the step on its right:

* a step that uses ``_`` gets the value wherever ``_`` appears; ``_`` may be
  used several times and as ``*_`` or ``**_``.  The step can be any
  expression: ``xs | [x * 2 for x in _]``, ``d | _["key"]``, ``n | _ + 1``;
* a call without ``_`` gets the value as its last positional argument:
  ``xs | map(f)`` is ``map(f, xs)``, ``xs | sorted(key=len)`` is
  ``sorted(xs, key=len)``;
* any other step is called with the value: ``x | chr`` is ``chr(x)``.

The value is evaluated once, and before the step, whatever the step does
with it.  Pipes nest: in ``a | f(_, (b | g(_)))`` the second ``_`` is ``b``.
A lambda with a parameter named ``_`` (or a comprehension looping over
``_``) keeps its own ``_``.

``|`` is left alone in annotations, ``type`` statements, ``|=`` and
``case a | b`` patterns.  Everywhere else in the block it is a pipe, so
for a bitwise or set/dict union use ``operator.or_(a, b)`` or leave the block.
"""

import ast
import macros

__all__ = ["pipe"]

PLACEHOLDER = "_"

_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
# Steps without a placeholder that can never be called.
_NOT_CALLABLE = (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict,
                 ast.JoinedStr, *_COMPREHENSIONS)
if hasattr(ast, "TemplateStr"):
    _NOT_CALLABLE += (ast.TemplateStr,)


def _error(message, node):
    exc = SyntaxError(message)
    exc.lineno = node.lineno
    exc.offset = node.col_offset + 1
    exc.end_lineno = getattr(node, "end_lineno", None)
    end = getattr(node, "end_col_offset", None)
    exc.end_offset = None if end is None else end + 1
    return exc


def _binds_placeholder(target):
    return any(isinstance(n, ast.Name) and n.id == PLACEHOLDER
               for n in ast.walk(target))


def _slots(node, out, parent=None, field=None, index=None):
    """Collect the places (parent, field, index) of *node* where the
    placeholder is used, leaving out the scopes that define their own."""
    if isinstance(node, ast.Name):
        if node.id == PLACEHOLDER and isinstance(node.ctx, ast.Load):
            out.append((parent, field, index))
        return
    if isinstance(node, ast.Lambda):
        a = node.args
        params = a.posonlyargs + a.args + a.kwonlyargs
        params += [p for p in (a.vararg, a.kwarg) if p is not None]
        if any(p.arg == PLACEHOLDER for p in params):
            # only the defaults are evaluated outside of the lambda
            for f in ("defaults", "kw_defaults"):
                for i, d in enumerate(getattr(a, f)):
                    if d is not None:
                        _slots(d, out, a, f, i)
            return
    if isinstance(node, _COMPREHENSIONS):
        gens = node.generators
        if any(_binds_placeholder(g.target) for g in gens):
            # only the first iterable is evaluated outside
            _slots(gens[0].iter, out, gens[0], "iter")
            return
    for f in node._fields:
        value = getattr(node, f, None)
        if isinstance(value, ast.AST):
            _slots(value, out, node, f)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    _slots(item, out, node, f, i)


def _put(slot, new):
    parent, field, index = slot
    old = getattr(parent, field) if index is None else getattr(parent, field)[index]
    ast.copy_location(new, old)
    if index is None:
        setattr(parent, field, new)
    else:
        getattr(parent, field)[index] = new


def _simple(node):
    """True if evaluating *node* early cannot be told from evaluating it late."""
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _simple(node.value)
    if isinstance(node, ast.Lambda):
        return not node.args.defaults and not any(node.args.kw_defaults)
    return False


def _direct(step, slots):
    """Can the value be written straight into the call *step* (no temporary)
    and still be evaluated once and before everything else in the step?"""
    if not isinstance(step, ast.Call) or not _simple(step.func):
        return False
    if not slots:                       # appended after the positional args
        return all(_simple(a) for a in step.args)
    if len(slots) != 1:
        return False
    parent, field, index = slots[0]
    if parent is step and field == "args":
        before = step.args[:index]
    elif (isinstance(parent, ast.Starred) and parent in step.args):
        before = step.args[:step.args.index(parent)]
    elif isinstance(parent, ast.keyword) and parent in step.keywords:
        before = step.args + [k.value for k in
                              step.keywords[:step.keywords.index(parent)]]
    else:
        return False
    return all(_simple(a) for a in before)


class _Pipes(ast.NodeTransformer):

    def __init__(self, macro):
        self.macro = macro
        self.count = 0

    # -- places where | keeps its meaning ----------------------------------

    def visit_arg(self, node):
        return node

    def visit_TypeAlias(self, node):
        return node

    def visit_AnnAssign(self, node):
        if node.value is not None:
            node.value = self.visit(node.value)
        node.target = self.visit(node.target)
        return node

    def _function(self, node):
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.args = self.visit(node.args)       # defaults; visit_arg skips annotations
        node.body = [self.visit(s) for s in node.body]
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node):
        for f in ("decorator_list", "bases", "keywords", "body"):
            setattr(node, f, [self.visit(n) for n in getattr(node, f)])
        return node

    # -- the pipe -----------------------------------------------------------

    def visit_BinOp(self, node):
        self.generic_visit(node)        # inner pipes first
        if not isinstance(node.op, ast.BitOr):
            return node
        value, step = node.left, node.right
        slots = []
        # a Name step is handled through a holder so that it has a parent
        holder = ast.Expr(step)
        _slots(step, slots, holder, "value")

        if not slots and not isinstance(step, ast.Call):
            if isinstance(step, _NOT_CALLABLE):
                raise _error(f"this pipe step cannot receive a value: it "
                             f"does not use '{PLACEHOLDER}' and is not "
                             f"callable", step)

        if slots and _direct(step, slots):
            _put(slots[0], value)
            return step
        if not slots and _direct(step, slots):
            step.args.append(value)
            return step
        if not slots and not isinstance(step, ast.Call) and _simple(step):
            return ast.copy_location(ast.Call(step, [value], []), node)

        # General case:  ($tmp = value; step using $tmp)
        self.count += 1
        tmp = macros.new_name(node, f"pipe{self.count}")
        if slots:
            for slot in slots:
                _put(slot, ast.Name(tmp, ast.Load()))
            result = holder.value
        else:
            arg = ast.copy_location(ast.Name(tmp, ast.Load()), value)
            if isinstance(step, ast.Call):
                step.args.append(arg)
                result = step
            else:
                result = ast.copy_location(ast.Call(step, [arg], []), node)
        target = ast.copy_location(ast.Name(tmp, ast.Store()), value)
        assign = ast.copy_location(ast.Assign([target], value), value)
        return ast.copy_location(ast.StmtExpr(assign, result), node)


@macros.macro_processor(macros.STMT_MACRO, 1)
def pipe(node):
    """``pipe!:`` block, or ``pipe! expression`` on one line."""
    if node.importname is not None or node.asname is not None:
        raise SyntaxError("pipe! does not accept 'import' or 'as'")
    transformer = _Pipes(node)
    if node.args is not None:
        if node.body:
            raise SyntaxError("use either 'pipe!:' with a block or "
                              "'pipe! expression', not both")
        return ast.copy_location(ast.Expr(transformer.visit(node.args)), node)
    if not node.body:
        raise SyntaxError("pipe! needs a block or an expression")
    return [transformer.visit(stmt) for stmt in node.body]


def _map(node):
    """``map!(expression)``: a function that maps *expression*, in which
    ``_`` is the item, over an iterable."""
    body = node.args
    if body is None:
        raise SyntaxError("map! needs an expression: map!(_ * 2)")
    if isinstance(body, ast.Starred):
        raise _error("map! takes an expression, not a starred expression",
                     body)
    def args(name):
        return ast.arguments(posonlyargs=[], args=[ast.arg(name)],
                             kwonlyargs=[], kw_defaults=[], defaults=[])
    it = macros.new_name(node, "items")
    item = ast.Lambda(args(PLACEHOLDER), body)
    call = ast.Call(ast.Name("map", ast.Load()),
                    [item, ast.Name(it, ast.Load())], [])
    return ast.Lambda(args(it), call)
 
 
# Defined last: from here on "map" is not the builtin in this module.
map = macros.macro_processor(macros.EXPR_MACRO, 1)(_map)
