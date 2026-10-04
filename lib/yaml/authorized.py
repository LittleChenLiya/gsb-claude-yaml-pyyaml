"""
Authorized SafeLoader for PyYAML.

This module provides :class:`AuthorizedSafeLoader`, a SafeLoader subclass that
enforces per-load tag authorization.  When extending SafeLoader with custom
tags, an authorization list can be supplied for each load: only the tag
constructors in the list (plus the standard safe YAML tags) are allowed to
execute.  The constructor table is frozen when the loader is instantiated, so
constructors registered later by other modules cannot leak into a load.
Python object construction is never permitted.

The global ``SafeLoader`` table is never modified, and the existing default
load entries (``yaml.safe_load``, ``yaml.load(stream, SafeLoader)``, etc.)
keep their original behaviour.
"""

__all__ = ['AuthorizedSafeLoader', 'authorized_safe_loader']

from .constructor import ConstructorError
from .loader import SafeLoader

# Standard safe YAML tags that are always permitted.  These are the tags that
# SafeConstructor registers by default; they do not need to appear in the
# authorization list.
_SAFE_TAGS = frozenset({
    'tag:yaml.org,2002:null',
    'tag:yaml.org,2002:bool',
    'tag:yaml.org,2002:int',
    'tag:yaml.org,2002:float',
    'tag:yaml.org,2002:binary',
    'tag:yaml.org,2002:timestamp',
    'tag:yaml.org,2002:omap',
    'tag:yaml.org,2002:pairs',
    'tag:yaml.org,2002:set',
    'tag:yaml.org,2002:str',
    'tag:yaml.org,2002:seq',
    'tag:yaml.org,2002:map',
})

# Prefix for Python object construction tags.  These are never permitted,
# regardless of the authorization list.
_PYTHON_TAG_PREFIX = 'tag:yaml.org,2002:python/'


class AuthorizedSafeLoader(SafeLoader):
    """
    A SafeLoader that enforces per-load tag authorization.

    Only tags in :attr:`allowed_tags` (plus the standard safe YAML tags) can
    be constructed.  The constructor table is frozen when the loader is
    instantiated, so constructors registered after creation cannot leak into
    a load.  Python object construction is never permitted.

    Use :func:`authorized_safe_loader` to create a loader class with a
    specific authorization list.
    """

    # Tags explicitly authorized for this loader.  Subclasses created by
    # :func:`authorized_safe_loader` set this.
    allowed_tags = frozenset()

    def __init__(self, stream):
        super().__init__(stream)
        # Freeze the constructor table at creation time so that constructors
        # registered later (e.g. by other modules) cannot leak into this load.
        # Copying to instance attributes shadows the class-level table.
        self.yaml_constructors = dict(self.__class__.yaml_constructors)
        self.yaml_multi_constructors = dict(self.__class__.yaml_multi_constructors)

    def construct_object(self, node, deep=False):
        tag = node.tag
        # Never allow python object construction, regardless of authorization.
        if tag.startswith(_PYTHON_TAG_PREFIX):
            raise ConstructorError(
                "while constructing a Python object", node.start_mark,
                "python object construction is not permitted", node.start_mark)
        # Allow standard safe tags and explicitly authorized custom tags.
        if tag not in _SAFE_TAGS and not self._is_authorized(tag):
            raise ConstructorError(
                "while constructing a node", node.start_mark,
                "tag %r is not in the authorization list" % tag,
                node.start_mark)
        return super().construct_object(node, deep=deep)

    def _is_authorized(self, tag):
        if tag in self.allowed_tags:
            return True
        # Support multi-constructor prefixes: a tag is authorized if it starts
        # with an authorized prefix.
        for prefix in self.allowed_tags:
            if tag.startswith(prefix):
                return True
        return False


def authorized_safe_loader(allowed_tags=()):
    """
    Create a SafeLoader subclass that only allows the given custom tags.

    The standard safe YAML tags are always available.  Python object
    construction is never permitted.  The constructor table is frozen when
    the loader is instantiated, so constructors registered after creation
    cannot leak into a load.

    ``allowed_tags`` is an iterable of tag strings (or tag prefixes for
    multi-constructors) that are permitted.

    Example::

        >>> import yaml
        >>> from yaml import authorized_safe_loader
        >>> class Point:
        ...     def __init__(self, x, y):
        ...         self.x = x
        ...         self.y = y
        ...
        >>> def point_constructor(loader, node):
        ...     values = loader.construct_mapping(node)
        ...     return Point(**values)
        ...
        >>> yaml.add_constructor('!Point', point_constructor, Loader=yaml.SafeLoader)
        >>> loader_cls = authorized_safe_loader(['!Point'])
        >>> yaml.load('!Point {x: 1, y: 2}', Loader=loader_cls)  # doctest: +SKIP
    """
    allowed = frozenset(allowed_tags)

    class _AuthorizedSafeLoader(AuthorizedSafeLoader):
        allowed_tags = allowed
        # Freeze the constructor table at class creation time.  This copy is
        # independent of the global SafeLoader table, so later registrations
        # on SafeLoader do not affect this class.
        yaml_constructors = dict(SafeLoader.yaml_constructors)
        yaml_multi_constructors = dict(SafeLoader.yaml_multi_constructors)

    return _AuthorizedSafeLoader
