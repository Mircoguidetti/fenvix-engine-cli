"""E4 (review R-003): every callable detpy replaces on a module keeps the
binding behaviour of the original, checked over the patcher's whole undo log
(time, os, random, socket, threading, glob, numpy... whatever is installed)."""


def test_every_replaced_module_callable_keeps_its_binding(pytester, run_det):
    pytester.makepyfile(
        test_all="""
        import types
        from detpy import plugin
        from detpy._patch import _MISSING

        class _Probe:
            pass

        def binds_as_method(obj):
            if isinstance(obj, type):
                return False
            _Probe.attr = obj
            try:
                return _Probe().attr is not obj
            finally:
                del _Probe.attr

        def test_binding_preserved():
            checked, wrong = 0, []
            for obj, name, original in plugin._PATCHER._undo:
                if not isinstance(obj, types.ModuleType) or original is _MISSING or not callable(original):
                    continue
                current = getattr(obj, name)
                if current is original:
                    continue
                checked += 1
                if binds_as_method(current) != binds_as_method(original):
                    wrong.append(f"{obj.__name__}.{name}")
            assert checked >= 20, checked
            assert not wrong, wrong
        """
    )
    result, _ = run_det("-p", "no:randomly")
    result.assert_outcomes(passed=1)
