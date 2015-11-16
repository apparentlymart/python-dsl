
def Enum(*names):
    """
    Creates an enumeration type.

    This can be used to accept predefined keywords in places where scalars
    are expected.
    """
    def __init__(self, name):
        self.name = name
    def __str__(self):
        return self.name
    d = {
        "__init__": __init__,
        "__str__": __str__,
    }
    bases = (object,)
    name = "Enum<%s>" % ",".join(names)
    t = type(name, bases, d)
    for name in names:
        setattr(t, name, t(name))
    return t
