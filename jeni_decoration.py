from collections import defaultdict
import functools
import sys

import jeni
import six


DECORATE = 'decorate'
CONFIGURE = 'configure'


class DecoratingInjector(jeni.Injector):
    @classmethod
    def decorate(cls, note, fn=None, **kw):
        '''Add decoration to be applied to an instance of note.

        Two mode of decoration are supported: decorate, and configure.

        Decorate mode is functional, the intermediate value of the note is
        passed in and what is returned then becomes the new value of the note.

        In configure mode, the return value is discarded.
        '''
        mode = kw.pop('mode', DECORATE)
        for k in kw:
            raise TypeError(
                    'decorate() got an unexpected keyword argument {!r}'
                    .format(k))
        if fn is None:
            return functools.partial(cls.decorate, note, mode=mode)
        if mode not in (DECORATE, CONFIGURE):
            raise ValueError(
                    'Invalid decorate() mode {!r}'
                    .format(mode))
        basenote, name = cls.parse_note(note)
        if mode == CONFIGURE and name is not None:
            raise ValueError(
                    'Decorating named notes in configure mode not supported')
        if 'decorator_registry' not in vars(cls):
            cls.decorator_registry = defaultdict(list)
        cls.decorator_registry[basenote, name].append((mode, fn))
        return fn

    def decorators_iter(self, basenote, name=None):
        """Iterate over partially applied decorators for a basenote."""
        # Walk method resolution order in reverse, first/outer decorators get
        # processed first.
        for c in type(self).mro()[::-1]:
            if 'decorator_registry' not in vars(c):
                # class is a mixin, super to base class, or never registered.
                continue
            if (basenote, name) in c.decorator_registry:
                # one or more decorators found
                for mode, fn in c.decorator_registry[basenote, name]:
                    if self.has_annotations(fn):
                        yield mode, self.partial(fn)
                    else:
                        yield mode, fn

    def decorators_apply(self, basenote, name, value):
        """Apply decorators to a value for a note."""
        for mode, fn in self.decorators_iter(basenote, name):
            if mode == DECORATE:
                value = fn(value)
            elif mode == CONFIGURE:
                fn(value)
        return value

    @classmethod
    def configure(cls, note, fn=None):
        '''Add configuration to be applied to an instance of note.'''
        return cls.decorate(note, fn, mode=CONFIGURE)

    def _handle_provider(self, provider_factory, note, basenote, name):
        # NOTE: The only changes are are the added calls to decorators_apply().
        if basenote not in self.instances:
            if (isinstance(provider_factory, type) and
                    self.has_annotations(provider_factory.__init__)):
                args, kwargs = self.prepare_callable(provider_factory.__init__)
                self.instances[basenote] = provider_factory(*args, **kwargs)

            else:
                self.instances[basenote] = self.apply_regardless(
                        provider_factory)

        provider = self.instances[basenote]
        get = self.partial_regardless(provider.get)

        try:
            if name is not None:
                value = get(name=name)
                value = self.decorators_apply(basenote, name, value)
                return value
            value = get()
            value = self.decorators_apply(basenote, None, value)
            self.values[basenote] = value
            return value

        except jeni.UnsetError:
            # Use sys.exc_info to support both Python 2 and Python 3.
            exc_type, exc_value, tb = sys.exc_info()
            exc_msg = str(exc_value)
            if exc_msg:
                msg = '{}: {!r}'.format(exc_msg, note)
            else:
                msg = repr(note)
            six.reraise(exc_type, exc_type(msg, note=note), tb)
