
class ContextMeta(type):
    pass


class Context(object):
    __metaclass__ = ContextMeta


def builder(*kwargs):
    pass


def single(block_type=None, *kwargs):
    pass


def multiple(block_type=None, *kwargs):
    pass

