
import numpy
from pytest import mark

from myia.abstract import from_value
from myia.pipeline import scalar_debug_pipeline, standard_debug_pipeline
from myia.composite import list_map
from myia.debug.label import short_labeler as lbl
from myia.debug.traceback import print_inference_error
from myia.abstract import InferenceError
from myia.prim.py_implementations import \
    hastype, partial, scalar_add, scalar_sub, \
    scalar_usub, scalar_uadd, switch, array_map
from myia.validate import ValidationError
from myia.utils import overload

from .common import mysum, i64, f64, Point


specialize_pipeline = scalar_debug_pipeline \
    .select('parse', 'infer', 'specialize',
            'erase_class', 'erase_tuple',
            'validate', 'export', 'wrap')


specialize_pipeline_std = standard_debug_pipeline \
    .select('parse', 'infer', 'specialize',
            'erase_class', 'opt', 'erase_tuple',
            'validate', 'export', 'wrap')


@overload
def _eq(t1: tuple, t2):
    return (isinstance(t2, tuple)
            and all(_eq(x1, x2) for x1, x2 in zip(t1, t2)))


@overload  # noqa: F811
def _eq(a1: numpy.ndarray, a2):
    return (a1 == a2).all()


@overload  # noqa: F811
def _eq(x: object, y):
    return x == y


def specializer_decorator(pipeline):
    def specialize(*arglists):

        def decorate(fn):
            def run_test(args):
                pip = pipeline.make()
                argspec = tuple(from_value(arg, broaden=True) for arg in args)

                result_py = fn(*args)

                try:
                    res = pip(input=fn, argspec=argspec)
                except InferenceError as ierr:
                    print_inference_error(ierr)
                    raise ierr
                except ValidationError as verr:
                    print('Collected the following errors:')
                    for err in verr.errors:
                        n = err.node
                        nlbl = lbl.label(n)
                        print(f'   {nlbl} ({type(n).__name__}) :: {n.type}')
                        print(f'      {err.args[0]}')
                    raise verr

                result_final = res['output'](*args)
                assert _eq(result_py, result_final)

            m = mark.parametrize('args', arglists)(run_test)
            m.__orig__ = fn
            return m

        return decorate
    return specialize


specialize = specializer_decorator(specialize_pipeline)
specialize_std = specializer_decorator(specialize_pipeline_std)


int1 = 13
int2 = 21

fp1 = 2.7
fp2 = 6.91


@specialize((int1, int2),
            (fp1, fp2))
def test_prim_mul(x, y):
    return x * y


@specialize((int1, int2),
            (fp1, int1))
def test_polymorphic(x, y):
    def helper(a, b):
        return a * a + b * b
    return helper(x, x + x), helper(y, y + y)


@specialize((int1, int2),
            (fp1, int1))
def test_polymorphic_closure(x, y):
    def construct(z):
        def inner(w):
            return z + w
        return inner
    return construct(x + x)(x), construct(y + y)(y)


@specialize((True, int1, int2),
            # (True, fp1, int1)  # TODO: mark this one as xfail
            )
def test_switch_fn(c, x, y):
    def dee(y):
        return y * y

    def doo(y):
        return y + y

    if c:
        f = dee
    else:
        f = doo

    return f(x), f(y)


@specialize((int1, int2), (int1, fp1))
def test_while(n, x):
    rval = x
    while n > 0:
        n = n - 1
        rval = rval - x
    return rval


@specialize((int1,), (fp1,))
def test_pow10(x):
    v = x
    j = 0
    while j < 3:
        i = 0
        while i < 3:
            v = v * x
            i = i + 1
        j = j + 1
    return v


@specialize((int1, fp1))
def test_hastype(x, y):
    def helper(x):
        if hastype(x, i64):
            return x
        elif hastype(x, f64):
            return x
        else:
            return (x,)

    return helper(x), helper(y), helper(())


@specialize((int1, int2))
def test_struct(x, y):
    return Point(x, y)


@specialize((int1, int2))
def test_struct2(x, y):
    p = Point(x, y)
    return p.x + p.y


@specialize((numpy.array([fp1, fp2]),))
def test_array_map(xs):
    def square(x):
        return x * x

    return array_map(square, xs)


@specialize((numpy.array([fp1, fp2]),
             numpy.array([int1, int2])))
def test_array_map_polymorphic(xs, ys):
    def square(x):
        return x * x

    return array_map(square, xs), array_map(square, ys)


@specialize(([fp1, fp2],))
def test_list_map(xs):
    def square(x):
        return x * x

    return list_map(square, xs)


@specialize(([fp1, fp2], [int1, int2]))
def test_list_map_polymorphic(xs, ys):
    def square(x):
        return x * x

    return list_map(square, xs), list_map(square, ys)


@mark.xfail(reason="Cannot specialize f.")
@specialize((True, [fp1, fp2], [int1, int2]))
def test_list_map_polymorphic_2(c, xs, ys):
    def square(x):
        return x * x

    def double(x):
        return x + x

    if c:
        f = square
    else:
        f = double

    return list_map(f, xs), list_map(f, ys)


@specialize((int1, int2))
def test_unused_parameter(x, y):
    return x * x


@specialize((int1,))
def test_unused_function_parameter(x):
    # The type of square will be Problem(DEAD), but that's not really an issue
    # because it is indeed not used, and we can simply replace the reference
    # by a dummy.
    def square(y):
        return y * y

    def helper(f, a):
        return a * a
    return helper(square, x)


@specialize((int1,))
def test_indirect_primitive(x):
    def add2():
        return scalar_add

    return add2()(x, x)


@specialize((int1,))
def test_indirect_graph(x):
    def f(x):
        return x * x

    def f2():
        return f

    return f2()(x)


@specialize((True, int1, int2))
def test_poly_with_constants(c, x, y):
    def f1(x, y):
        return x + y

    def f2(x, y):
        return x * y

    def choose(c):
        if c:
            return f1
        else:
            return f2

    return choose(c)(x, y), choose(not c)(x, y)


@specialize((True, int1, int2))
def test_poly_with_constants2(c, x, y):
    def f1(x, y):
        return x + y

    def f2(x, y):
        return x * y

    def choose(c):
        if c:
            return f1
        else:
            return f2

    return choose(c)(x, 2), choose(not c)(y, 3)


@specialize((int1, int2), (fp1, fp2))
def test_method(x, y):
    return x.__add__(y)


@specialize((int1, fp1))
def test_method_polymorphic(x, y):
    return x.__add__(x), y.__add__(y)


@specialize((int1, fp1))
def test_partial_polymorphic(x, y):
    def f(a, b):
        return a + b
    return partial(f, x)(x), partial(f, y)(y)


@specialize((True, int1), (False, int1))
def test_switch(c, x):
    return switch(c, scalar_usub, scalar_uadd)(x)


@specialize((True, int1, int2), (False, int1, int2))
def test_switch2(c, x, y):
    fn = switch(
        c,
        partial(scalar_sub, x),
        partial(scalar_add, x)
    )
    return fn(y)


@specialize((int1, int2, int2))
def test_multitype(x, y, z):
    return mysum(x) * mysum(x, y) * mysum(x, y, z)


@specialize((int1, int2))
def test_closure_stays_in_scope(x, y):
    # The inferrer knows that h(x + y) is the graph for g, but
    # it shouldn't try to replace the expression with that graph,
    # because it points to a fv in f.
    def f(z):
        def g():
            return z
        return g

    def h(z):
        a = z * z
        return f(a)

    return h(x + y)()


@specialize((int1,))
def test_return_closure(x):
    # The specializer should be careful not to replace `f(z - 1)[0]`
    # by a reference to `g`, because `g` is closed over `z` whereas
    # `f(z - 1)[0]` refers to a version of `g` closed on `z - 1`.
    def f(z):
        def g():
            return z

        def h():
            return f(z - 1)[0]()
        return (g, h)

    return f(x)[1]()


@specialize((int1, int2))
def test_partial_outside_scope(x, y):
    # The inferrer knows that g(x) is a partial of f, but it can't
    # build it inside the main function.
    def f(x, y):
        return x * y

    def g(x):
        z = x * x
        return partial(f, z)

    return g(x)(y)
