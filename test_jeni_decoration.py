import sys
if sys.version_info >= (3,):
    import unittest
    import unittest.mock as mock
else:
    import unittest2 as unittest
    import mock

import jeni
from jeni_decoration import DecoratingInjector


class TestInjectorDecorations(unittest.TestCase):
    def setUp(self):
        class TestInjector(DecoratingInjector): pass
        self.Injector = TestInjector
        class SubTestInjector(TestInjector): pass
        self.SubInjector = SubTestInjector
        @self.Injector.provider('genie', name=True)
        class TestGenie(jeni.Provider):
            @jeni.annotate('genie-d')
            def get(self, d, name=None):
                return d.get(name) if name is not None else d

    def test_decorate_not_defined(self):
        not_called = mock.Mock()
        self.Injector.decorate('not-defined', not_called)

        with self.Injector() as inj:
            inj # pyflakes
        self.assertEqual(not_called.call_count, 0)

    def test_simple_decorate(self):
        reverse_it = mock.Mock(side_effect=lambda v: v[::-1])
        self.Injector.value('it', 'abc')
        self.Injector.decorate('it', reverse_it)

        with self.Injector() as inj:
            self.assertEqual(inj.get('it'), 'cba')
            # double check, to make sure the cache has the right value
            self.assertEqual(inj.get('it'), 'cba')
        reverse_it.assert_called_once_with('abc')

    def test_simple_configure(self):
        ignore_it = mock.Mock()
        self.Injector.value('it', 'abc')
        self.Injector.configure('it')(ignore_it)

        with self.Injector() as inj:
            self.assertEqual(inj.get('it'), 'abc')
        ignore_it.assert_called_once_with('abc')

    def test_multiple_decorate(self):
        self.Injector.value('it', 'abc')
        reverse_it = mock.Mock(side_effect=lambda v: v[::-1])
        self.Injector.decorate('it', reverse_it)
        double_it = mock.Mock(side_effect=lambda v: v+v)
        self.Injector.decorate('it', double_it)

        with self.Injector() as inj:
            self.assertEqual(inj.get('it'), 'cbacba')
        with self.subTest(
                'decorators are called in the order they are registered'):
            reverse_it.assert_called_once_with('abc')
            double_it.assert_called_once_with('cba')

    def test_mixed_mode_decorate(self):
        self.Injector.value('it', 'abc')
        reverse_it = mock.Mock(side_effect=lambda v: v[::-1])
        self.Injector.decorate('it', reverse_it)
        ignore_it = mock.Mock()
        self.Injector.configure('it', ignore_it)
        double_it = mock.Mock(side_effect=lambda v: v+v)
        self.Injector.decorate('it', double_it)

        with self.Injector() as inj:
            self.assertEqual(inj.get('it'), 'cbacba')
        with self.subTest(
                'decorators are called in the order they are registered'):
            reverse_it.assert_called_once_with('abc')
            ignore_it.assert_called_once_with('cba')
            double_it.assert_called_once_with('cba')

    def test_annotated_decorate(self):
        self.Injector.value('it', 'abc')
        @jeni.annotate(three='3')
        def reverse_it_(it, three):
            return it[::-1]
        reverse_it = mock.Mock(side_effect=reverse_it_)
        reverse_it.__notes__ = reverse_it_.__notes__
        self.Injector.decorate('it', reverse_it)

        with self.assertRaises(Exception),\
            self.Injector() as inj:
            inj.get('it')

        reverse_it.reset_mock()
        self.Injector.value('3', 3)

        with self.Injector() as inj:
            self.assertEqual(inj.get('it'), 'cba')
        reverse_it.assert_called_once_with('abc', three=3)

    def test_nested_decorate(self):
        self.Injector.value('it', 'abc')
        reverse_it = mock.Mock(side_effect=lambda v: v[::-1])
        self.Injector.decorate('it', reverse_it)
        double_it = mock.Mock(side_effect=lambda v: v+v)
        self.SubInjector.decorate('it', double_it)

        with self.Injector() as inj:
            self.assertEqual(inj.get('it'), 'cba')
        reverse_it.assert_called_once_with('abc')
        self.assertEqual(double_it.call_count, 0)

        reverse_it.reset_mock()

        with self.SubInjector() as inj:
            self.assertEqual(inj.get('it'), 'cbacba')
        with self.subTest(
                'decorators from base injectors are called before decorators '
                'from subinjectors'):
            reverse_it.assert_called_once_with('abc')
            double_it.assert_called_once_with('cba')

    def test_decorate_named(self):
        self.Injector.value('genie-d', dict(
                foo='foo',
                bar='bar'))
        double_it = mock.Mock(side_effect=lambda v: v+v)
        self.Injector.decorate('genie:foo', double_it)

        with self.Injector() as inj:
            self.assertEqual(inj.get('genie:foo'), 'foofoo')
            self.assertEqual(inj.get('genie').get('foo'), 'foo')
            self.assertEqual(inj.get('genie:bar'), 'bar')

    def test_configure_named_unsupported(self):
        ignore_it = mock.Mock()
        with self.assertRaises(Exception):
            self.Injector.configure('genie:foo', ignore_it)
