# jeni.py
# Copyright 2013-2014 Ron DuPlain <ron.duplain@gmail.com> (see AUTHORS file).
# Released under the BSD License (see LICENSE file).

"""jeni: dependency injection through annotations (dip)."""

__version__ = '0.3-dev'

import abc
import functools
import inspect
import re
import sys

import six


# TODO: Update all docstrings and rewrite test_jeni.py.

class UnsetError(LookupError):
    """Note is not able to be provided, as it is currently unset."""
    def __init__(self, *a, **kw):
        self.note = kw.pop('note', None)
        super(UnsetError, self).__init__(*a, **kw)


# Motivation: dependency injection using prepared providers.

@six.add_metaclass(abc.ABCMeta)
class Provider(object):
    @abc.abstractmethod
    def get(self, name=None):
        return

    def close(self):
        return


class GeneratorProvider(Provider):
    def __init__(self, function, support_name=False):
        self.function = function
        self.support_name = support_name

    def init(self, *a, **kw):
        self.generator = self.function(*a, **kw)
        try:
            self.init_value = next(self.generator)
        except StopIteration:
            msg = "generator didn't yield: function {!r}"
            raise RuntimeError(msg.format(self.function))
        else:
            return self.init_value

    def get(self, name=None):
        if name is None:
            return self.init_value
        elif not self.support_name:
            msg = "generator does not support get-by-name: function {!r}"
            raise TypeError(msg.format(self.function))
        try:
            value = self.generator.send(name)
        except StopIteration:
            msg = "generator didn't yield: function {!r}"
            raise RuntimeError(msg.format(self.function))
        return value

    def close(self):
        if self.support_name:
            self.generator.close()
        try:
            next(self.generator)
        except StopIteration:
            return
        else:
            msg = "generator didn't stop: function {!r}"
            raise RuntimeError(msg.format(self.function))


class Injector(object):
    """Collects dependencies and reads annotations to fulfill them."""
    generator_provider = GeneratorProvider
    re_note = re.compile(r'^(.*?)(?::(.*))?$') # annotation is 'object:name'

    def __init__(self):
        self.closed = False
        self.instances = {}
        self.values = {}

    @classmethod
    def provider(cls, note, provider=None, name=False):
        def decorator(fn_or_class):
            if inspect.isgeneratorfunction(fn_or_class):
                fn = fn_or_class
                fn.support_name = name
                cls.register(note, fn)
            else:
                provider = fn_or_class
                if not hasattr(provider, 'get'):
                    msg = "{!r} does not meet provider interface with 'get'"
                    raise ValueError(msg.format(provider))
                cls.register(note, provider)
            return fn_or_class
        if provider is not None:
            decorator(provider)
        else:
            return decorator

    @classmethod
    def factory(cls, note, fn=None):
        if fn is not None:
            cls.register(note, fn)
        else:
            def decorator(f):
                cls.register(note, f)
                return f
            return decorator

    def apply(self, fn):
        args, kwargs = self.prepare(fn)
        return fn(*args, **kwargs)

    def partial(self, fn):
        args, kwargs = self.prepare(fn)
        return functools.partial(fn, *args, **kwargs)

    def close(self):
        # TODO: have an opinion about order of closed
        # TODO: keeping counts on tokens resolved, not just bool, would be nice
        if self.closed:
            raise RuntimeError('{!r} already closed'.format(self))
        for provider in self.instances.values():
            provider.close()
        self.closed = True

    def prepare(self, fn):
        notes, keyword_notes = collect_notes(fn)
        args, kwargs = self.fulfill(*notes, **keyword_notes)
        return args, kwargs

    def fulfill(self, *notes, **keyword_notes):
        """Fulfill injection during function application."""
        args = tuple(self.resolve(note) for note in notes)
        kwargs = {}
        for arg in keyword_notes:
            # TODO: Maybe.
            note = keyword_notes[arg]
            try:
                kwargs[arg] = self.resolve(note)
            except UnsetError:
                continue
        return args, kwargs

    def resolve(self, note):
        """Resolve a single note into an object."""
        basenote, name = self.parse_note(note)
        if name is None and basenote in self.values:
            return self.values[basenote]
        try:
            provider_or_fn = self.lookup(basenote)
        except LookupError:
            msg = "Unable to resolve '{}'"
            raise LookupError(msg.format(note))
        return self.handle_provider(provider_or_fn, note, basenote, name=name)

    def handle_provider(self, provider_or_fn, note, basenote, name=None):
        if basenote in self.instances:
            provider_or_fn = self.instances[basenote]
        elif inspect.isclass(provider_or_fn):
            provider_or_fn = provider_or_fn()
            self.instances[basenote] = provider_or_fn
        elif inspect.isgeneratorfunction(provider_or_fn):
            provider_or_fn, value = self.init_generator(provider_or_fn)
            self.instances[basenote] = provider_or_fn
            self.values[basenote] = value
            if name is None:
                return value
        if hasattr(provider_or_fn, 'get'):
            fn = provider_or_fn.get
        else:
            fn = provider_or_fn
        if has_annotations(fn):
            fn = self.partial(fn)
        try:
            if name is None:
                value = fn()
                self.values[basenote] = value
                return value
            return fn(name=name)
        except UnsetError:
            # Use sys.exc_info to support both Python 2 and Python 3.
            exc_type, exc_value, tb = sys.exc_info()
            exc_value.note = note
            six.reraise(exc_type, exc_value, tb)

    @classmethod
    def parse_note(cls, note):
        """Parse string annotation into object reference with optional name."""
        if isinstance(note, tuple):
            if len(note) != 2:
                raise ValueError('tuple annotations must be length 2')
            return note
        try:
            match = cls.re_note.match(note)
        except TypeError:
            # Note is not a string. Support any Python object as a note.
            return note, None
        return match.groups()

    @classmethod
    def register(cls, note, provider):
        basenote, name = cls.parse_note(note)
        if 'provider_registry' not in vars(cls):
            cls.provider_registry = {}
        cls.provider_registry[basenote] = provider

    @classmethod
    def lookup(cls, basenote):
        """Look up note in registered annotations, walking class tree."""
        # Walk method resolution order, which includes current class.
        for c in cls.mro():
            if 'provider_registry' not in vars(c):
                # class is a mixin, super to base class, or never registered.
                continue
            if basenote in c.provider_registry:
                # note is in the registry.
                return c.provider_registry[basenote]
        raise LookupError(repr(basenote))

    def init_generator(self, fn):
        provider = self.generator_provider(fn, support_name=fn.support_name)
        if has_annotations(provider.function):
            notes, keyword_notes = collect_notes(provider.function)
            args, kwargs = self.fulfill(*notes, **keyword_notes)
            value = provider.init(*args, **kwargs)
        else:
            value = provider.init()
        return provider, value

    # TODO: enter and exit as method and __method__


# Annotations provide key data for jeni's injection.

def annotate(*notes, **keyword_notes):
    """Decorator-maker to annotate a given callable."""
    # TODO: Support base-case to opt-in a function annotated in Python 3.
    def decorator(fn):
        set_annotations(fn, *notes, **keyword_notes)
        return fn
    return decorator


def set_annotations(fn, *notes, **keyword_notes):
    """Set the annotations on the given callable."""
    # TODO: Do not use __annotations__ since there are no standards.
    if getattr(fn, '__annotations__', None):
        raise AttributeError('callable is already annotated: {!r}'.format(fn))
    check_for_extras(fn, keyword_notes)
    annotations = {}
    annotations.update(keyword_notes)
    args = get_function_arguments(fn)
    if len(notes) > len(args):
        msg = '{!r} takes {} arguments, but {} annotations given'
        raise TypeError(msg.format(fn, len(args), len(notes)))
    for arg_name, note in zip(args, notes):
        annotations[arg_name] = note
    if hasattr(fn, '__func__'):
        fn.__func__.__annotations__ = annotations
    else:
        fn.__annotations__ = annotations


def get_annotations(fn):
    """Get the annotations of a given callable."""
    # TODO: Do not use __annotations__ since there are no standards.
    annotations = getattr(fn, '__annotations__', None)
    if annotations:
        return annotations
    raise AttributeError('{!r} does not have annotations'.format(fn))


def has_annotations(fn):
    """True if callable is annotated, else False."""
    try:
        get_annotations(fn)
    except AttributeError:
        return False
    return True


def collect_notes(fn):
    """Format callable's annotations into notes, keyword_notes."""
    annotations = get_annotations(fn)
    args, keywords = get_named_positional_keyword_arguments(fn)
    notes = []
    keyword_notes = {}
    for arg in args:
        try:
            notes.append(annotations[arg])
        except KeyError:
            break
    for arg in keywords:
        try:
            keyword_notes[arg] = annotations[arg]
        except KeyError:
            continue
    return tuple(notes), keyword_notes


def check_for_extras(fn, keyword_notes):
    """Raise TypeError if function has too many keyword annotations."""
    if supports_extra_keywords(fn):
        return
    args = get_function_arguments(fn)
    for arg in keyword_notes:
        if arg not in args:
            msg = "{}() got an unexpected keyword annotation '{}'"
            raise TypeError(msg.format(fn.__name__, arg))


# Inspect utilities allow for manipulation of annotations.

def class_in_progress(stack=None):
    """True if currently inside a class definition, else False."""
    if stack is None:
        stack = inspect.stack()
    for frame in stack:
        statement_list = frame[4]
        if statement_list is None:
            continue
        if statement_list[0].strip().startswith('class '):
            return True
    return False


getargspec = getattr(inspect, 'getfullargspec', inspect.getargspec)


def get_function_arguments(fn):
    """Provide function argument names, skipping method's 'self'."""
    args = getargspec(fn).args
    if class_in_progress():
        args = args[1:]
    if hasattr(fn, '__self__'):
        args = args[1:]
    return args


def get_named_positional_keyword_arguments(fn):
    """Provide named (not *, **) positional, keyword arguments of callable."""
    argspec = getargspec(fn)
    args = get_function_arguments(fn)
    keywords = {}
    for default in reversed(argspec.defaults or []):
        keywords[args.pop()] = default
    return tuple(args), keywords


def supports_extra_keywords(fn):
    """True if callable catches unnamed keyword arguments, else False."""
    if hasattr(inspect, 'getfullargspec'):
        return inspect.getfullargspec(fn).varkw is not None
    return inspect.getargspec(fn).keywords is not None


if __name__ == '__main__':
    @Injector.provider('answer')
    def fn():
        print('before')
        yield 42
        print('after')

    injector = Injector()
    print(Injector.provider_registry)
    print(injector.fulfill('answer'))
    print(injector.resolve('answer'))

    provider = GeneratorProvider(fn)
    provider.init()
    print(provider.get())
    print(provider.get())
    provider.close()

    Injector.provider(42, fn)
    print(injector.resolve(42))

    @Injector.provider('foo')
    class FooProvider(Provider):
        @annotate('bar', 'baz')
        def get(self, bar, baz, name=None):
            return bar, baz, 'foo'

    foo_provider = FooProvider()
    print(foo_provider.get('bar', 'baz'))
    print(collect_notes(foo_provider.get))

    @Injector.factory('error')
    def error():
        raise UnsetError

    @annotate('error')
    def positional_error(error):
        print('You should not see me.')

    @annotate('answer', unused='error')
    def keyword_error(answer, unused=None):
        assert unused is None

    try:
        injector.apply(positional_error)
    except UnsetError:
        err = sys.exc_info()[1]
        assert err.note == 'error'

    injector.apply(keyword_error)

    class SubInjector(Injector):
        pass

    SubInjector.factory('universe', fn)
    sub_injector = SubInjector()
    print(sub_injector.fulfill('answer'))

    @Injector.provider('generator')
    def generator():
        yield 'Hello, world!'
        print('generator closing')

    print('starting generator')
    print(injector.resolve('generator'))
    print(injector.resolve('generator'))
    try:
        print(injector.resolve('generator:name'))
    except TypeError:
        _, error, _ = sys.exc_info()
        print(error)
    else:
        assert False, "'generator:name' should have failed"

    @Injector.provider('generator_with_name', name=True)
    def generator_with_name():
        try:
            name = yield 'Hello, world!'
            while True:
                name = yield 'Hello, {}!'.format(name)
        finally:
            print('generator_with_name closing')

    print('starting generator_with_name')
    print(injector.resolve('generator_with_name'))
    print(injector.resolve('generator_with_name'))
    print(injector.resolve('generator_with_name:name_here'))
    print(injector.resolve('generator_with_name:name_there'))

    @Injector.provider('generator_with_name_and_annotations', name=True)
    @annotate('answer', unused='error')
    def generator_with_name_and_annotations(answer, unused=None):
        try:
            name = yield 'Hello, {}!'.format(answer)
            while True:
                name = yield 'Hello, {}!'.format(name)
        finally:
            print('generator_with_name_and_annotations closing')

    print('starting generator_with_name_and_annotations')
    print(injector.resolve('generator_with_name_and_annotations'))
    print(injector.resolve('generator_with_name_and_annotations'))
    print(injector.resolve('generator_with_name_and_annotations:name_here'))
    print(injector.resolve('generator_with_name_and_annotations:name_there'))

    injector.close()
