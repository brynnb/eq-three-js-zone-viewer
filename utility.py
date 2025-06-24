from itertools import chain


def interleave(*lists):
    return list(chain.from_iterable(zip(*lists)))


def flatten(x):
    while len(x) and isinstance(x[0], (tuple, list)):
        x = [item for sub in x for item in sub]
    return x
