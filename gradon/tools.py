import itertools


def tee_count(iter):
    """ Returns the a tuple of total entries plus a copy of the original iterator """
    countable, copy = itertools.tee(iter)
    return sum(1 for _ in countable), copy
