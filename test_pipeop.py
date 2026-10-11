import ast, macros, unittest, textwrap, operator
import pipeop

M = {"pipe": pipeop.pipe, "map": pipeop.map}

def run(src, **ns):
    ns.setdefault("log", [])
    exec(compile(textwrap.dedent(src), "<test>", "exec", macros=M), ns)
    return ns

def expand(src):
    return ast.unparse(macros.expand(ast.parse(textwrap.dedent(src)), macros=M))

def ev(name):
    def f(log, v=None):
        log.append(name); return v
    return f

class T(unittest.TestCase):
    def test_users_examples(self):
        ns = run("""
            import random
            pipe!:
                a = range(16) | map(lambda i: random.randint(ord('a'), ord('z')) | chr) | ''.join()
                b = range(16) | map(lambda i: random.randint(ord('a'), ord('z')) | chr, _) | ''.join(_) | len(_)
                c = range(4) | [x for x in _]
        """)
        self.assertTrue(len(ns["a"]) == 16 and ns["a"].isalpha() and ns["a"].islower())
        self.assertEqual(ns["b"], 16)
        self.assertEqual(ns["c"], [0, 1, 2, 3])

    def test_clean_expansion(self):
        self.assertEqual(expand("pipe!:\n  range(16) | map(f) | ''.join() | print()"),
                         "print(''.join(map(f, range(16))))")
        self.assertEqual(expand("pipe!:\n  x | f(1, _) | g(*_) | h(**_) | chr"),
                         "chr(h(**g(*f(1, x))))")
        self.assertEqual(expand("pipe! x | sorted(key=len)"), "sorted(x, key=len)")

    def test_multiple_and_star(self):
        ns = run("""
            def f(*a, **k): return a, k
            pipe!:
                a = [1, 2] | f(_, *_, _)
                b = {'p': 1} | f(**_, q=_)
                c = 3 | _ * _ + _
                d = {'k': 5} | _['k']
                e = 'abc' | _.upper() | f"<{_}>"
        """)
        self.assertEqual(ns["a"], (([1, 2], 1, 2, [1, 2]), {}))
        self.assertEqual(ns["b"], ((), {'p': 1, 'q': {'p': 1}}))
        self.assertEqual((ns["c"], ns["d"], ns["e"]), (12, 5, "<ABC>"))

    def test_evaluated_once_and_first(self):
        ns = run("""
            pipe!:
                r1 = A(log, 1) | (lambda *a: a)(B(log), _, _)
                r2 = A(log, 2) | F(log, lambda v: v + 1)(_)
                r3 = A(log, 3) | (lambda *a, **k: (a, k))(B(log, 0), k=C(log))
        """, A=ev("A"), B=ev("B"), C=ev("C"), F=ev("F"))
        self.assertEqual(ns["log"], ["A", "B", "A", "F", "A", "B", "C"])
        self.assertEqual(ns["r1"], (None, 1, 1))
        self.assertEqual(ns["r2"], 3)
        self.assertEqual(ns["r3"], ((0, 3), {"k": None}))

    def test_nesting_and_scopes(self):
        ns = run("""
            pipe!:
                a = 1 | (lambda x, y: (x, y))(_, (10 | _ + _))
                b = 2 | (_ | _ + 1) * 10
                c = [1, 2, 3] | map(lambda _: _ * 2) | list
                d = [1, 2] | [_ for _ in _]
                e = 5 | (lambda: _ + 1) | _()
                f = [3, 4] | [x + y for x in _ for y in _]
                def g(xs: int | None = (1 | float)) -> int | None:
                    v: int | str = xs | str
                    return v
                class K:
                    z = [1, 2] | sum | _ + _
                h = [[n | _ * 2 | str for n in row] for row in [[1], [2, 3]]]
                i = (j := 4 | _ + 1) | _ * j
        """)
        self.assertEqual(ns["a"], (1, 20)); self.assertEqual(ns["b"], 30)
        self.assertEqual(ns["c"], [2, 4, 6]); self.assertEqual(ns["d"], [1, 2])
        self.assertEqual(ns["e"], 6); self.assertEqual(ns["f"], [6, 7, 7, 8])
        self.assertEqual(ns["g"](), "1.0"); self.assertEqual(ns["K"].z, 6)
        self.assertEqual(ns["g"].__annotations__["xs"], int | None)
        self.assertEqual(ns["h"], [["2"], ["4", "6"]]); self.assertEqual(ns["i"], 25)

    def test_statements(self):
        ns = run("""
            import asyncio
            out = []
            pipe!:
                for x in range(3) | map(lambda v: v * v):
                    if x | bool:
                        x | out.append()
                def gen():
                    got = 1 | (yield _)
                    yield got | _ + 1
                async def co():
                    return 7 | (await asyncio.sleep(0, _)) | _ + 1
                s = {1}; s |= {2}
                match 3:
                    case 1 | 3: m = True
                t = operator.or_(1, 2)
            pipe! out | len | out.append()
            g = gen(); first = next(g); second = g.send(10)
            r = asyncio.run(co())
        """, operator=operator)
        self.assertEqual(ns["out"], [1, 4, 2]); self.assertEqual(ns["s"], {1, 2})
        self.assertEqual((ns["first"], ns["second"], ns["r"], ns["t"], ns["m"]), (1, 11, 8, 3, True))

    def test_outside_block_untouched(self):
        self.assertEqual(run("pipe!:\n  a = 1 | float\nb = 1 | 2")["b"], 3)

    def test_map_macro(self):
        ns = run("""
            import random
            def show(s): out.append(s)
            out = []
            pipe!:
                16 | range | map!(random.randint(ord('a'), ord('z')) | chr) | ''.join | show
                a = range(4) | map!(_ * _) | list
                b = [[1, 2], [3]] | map!(_ | map!(_ + 1) | sum) | list
                c = 10 | (range(3) | map!(_ + 1) | list) + [_]
                d = A(log, 'ab') | map!(_.upper(), _) | dict
                e = [1, 2] | map!(lambda k: _ + k) | map!(_(10)) | tuple
            f = list(map!(_ | 4)([1, 2]))
        """, A=ev("A"))
        self.assertTrue(len(ns["out"][0]) == 16 and ns["out"][0].isalpha())
        self.assertEqual(ns["a"], [0, 1, 4, 9]); self.assertEqual(ns["b"], [5, 4])
        self.assertEqual(ns["c"], [1, 2, 3, 10]); self.assertEqual(ns["d"], {"A": "a", "B": "b"})
        self.assertEqual(ns["e"], (11, 12)); self.assertEqual(ns["f"], [5, 6])
        self.assertEqual(ns["log"], ["A"])
        for bad in ("x = map!()", "x = map!(*a)"):
            with self.assertRaises(SyntaxError):
                run(bad)

    def test_errors(self):
        with self.assertRaises(SyntaxError) as cm:
            run("pipe!:\n    x = 1 | [2, 3]")
        self.assertEqual((cm.exception.lineno, cm.exception.offset), (2, 13))
        with self.assertRaises(SyntaxError):
            run("pipe! 1 | 'a'")

    def test_traceback_line(self):
        try:
            run("pipe!:\n    x = (1\n      | float\n      | _ / 0)")
        except ZeroDivisionError as e:
            tb = e.__traceback__
            while tb.tb_next: tb = tb.tb_next
            self.assertEqual(tb.tb_lineno, 4)
        else: self.fail()

unittest.main()
