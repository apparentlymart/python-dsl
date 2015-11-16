import unittest

import dsl


class TestEnum(unittest.TestCase):

    def test_create(self):
        enum1 = dsl.Enum("foo", "bar", "baz")
        enum2 = dsl.Enum("foo", "beep", "boop")
        self.assertNotEqual(enum1, enum2)
        self.assertNotEqual(enum1.foo, enum2.foo)
        self.assertEqual(type(enum1.foo), enum1)
        self.assertEqual(type(enum2.foo), enum2)
        self.assertEqual(str(enum1.foo), "foo")
        self.assertEqual(enum1.foo.name, "foo")
