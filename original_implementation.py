"""PyInstaller's original `iterate_instructions`, for comparison with the fast one in the checkout."""

import dis
import types


def iterate_instructions(code_object):
    """A copy of `PyInstaller.lib.modulegraph.util.iterate_instructions` before the fix."""
    yield from (i for i in dis.get_instructions(code_object) if i.opname != "EXTENDED_ARG")

    yield None

    for constant in code_object.co_consts:
        if isinstance(constant, types.CodeType):
            yield from iterate_instructions(constant)
