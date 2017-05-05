import difflib
import filecmp

import pytest


class ComparableFile(object):
    def __init__(self, path):
        self.path = path

    def __eq__(self, file):
        return filecmp.cmp(self.path, file.path)

    def lines(self):
        return open(self.path).readlines()


@pytest.fixture(scope="module")
def cmpfile():
    return ComparableFile


def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, ComparableFile) and isinstance(right, ComparableFile) and op == '==':
        return list(difflib.ndiff(left.lines(), right.lines()))
