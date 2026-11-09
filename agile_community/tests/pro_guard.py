"""Tests of a Free feature that also touch an agile_pro model skip themselves when agile_pro is not installed.

agile_pro runs the same methods again with every model present (see agile_pro/tests/test_free_with_pro.py).
"""
import functools


def needs_pro(*models):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            for model in models:
                if model not in self.env:
                    self.skipTest("needs agile_pro (%s)" % model)
            return func(self, *args, **kwargs)

        wrapper.needs_pro = True
        return wrapper

    return decorator
