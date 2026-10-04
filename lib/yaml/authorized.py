"""
Per-load authorized tag loading on top of SafeLoader.

This module lets a caller load an untrusted YAML stream with an explicit,
per-load authorization list ("allow-list") of custom tag constructors:

* The constructor table is *frozen* when the loader for this load is
  created.  Constructors registered by other modules afterwards -- or even
  while the load is in progress -- never enter the snapshot.
* The standard safe tags (``tag:yaml.org,2002:*`` except the ``python/*``
  family) remain available, exactly as with ``yaml.safe_load``.
* A custom tag that is not on the authorization list is rejected *before*
  its constructor runs, with an error carrying the line/column of the
  offending node.
* All documents of a multi-document stream share the same authorization
  snapshot.
* Authorization can never enable ``python/*`` object construction.
* The global ``SafeLoader`` constructor table is never modified, and the
  default entry points (``yaml.safe_load`` / ``yaml.safe_load_all``) keep
  their original behaviour.

Example
-------
    >>> import yaml
    >>> yaml.add_constructor('!Point', point_constructor)   # doctest: +SKIP
    >>> yaml.authorized_load("!Point [1, 2]", allowed_tags=['!Point'])
    Point(x=1, y=2)
"""

__all__ = [
    'AuthorizedLoaderError',
    'UnauthorizedTagError',
    'AuthorizedSafeLoader',
    'authorized_loader',
    'authorized_load',
    'authorized_load_all',
]

from .error import YAMLError
from .constructor import SafeConstructor, ConstructorError
from .loader import SafeLoader

_YAML_TAG_PREFIX = 'tag:yaml.org,2002:'
_PYTHON_TAG_PREFIX = 'tag:yaml.org,2002:python'


class AuthorizedLoaderError(YAMLError):
    """Base class for errors of the per-load authorization API."""


class UnauthorizedTagError(ConstructorError, AuthorizedLoaderError):
    """Raised when a document uses a tag that is not authorized for this load.

    The error carries the start mark (line/column) of the offending node.
    """


def _reject_unauthorized(self, node):
    raise UnauthorizedTagError(None, None,
            "tag %r is not authorized for this load" % node.tag,
            node.start_mark)


def _standard_safe_constructors():
    """Snapshot of the standard safe constructors of SafeLoader.

    Only the standard ``tag:yaml.org,2002:*`` tags (excluding the
    ``python/*`` family) are kept; anything else is considered a custom
    tag and requires explicit authorization.
    """
    table = {}
    for tag, constructor in SafeLoader.yaml_constructors.items():
        if tag is None:
            continue
        if tag.startswith(_PYTHON_TAG_PREFIX):
            continue
        if tag.startswith(_YAML_TAG_PREFIX):
            table[tag] = constructor
    return table


def _standard_safe_multi_constructors():
    table = {}
    for prefix, multi_constructor in SafeLoader.yaml_multi_constructors.items():
        if prefix.startswith(_PYTHON_TAG_PREFIX):
            continue
        if prefix.startswith(_YAML_TAG_PREFIX):
            table[prefix] = multi_constructor
    return table


def _validate_allowed_tags(allowed_tags):
    allowed = []
    for tag in allowed_tags:
        if not isinstance(tag, str):
            raise TypeError(
                    "authorized tags must be strings, got %r" % (tag,))
        if tag.startswith(_PYTHON_TAG_PREFIX):
            raise ValueError(
                    "authorization cannot enable python object construction: %r"
                    % tag)
        if tag.startswith(_YAML_TAG_PREFIX):
            raise ValueError(
                    "standard safe tag %r does not need authorization" % tag)
        allowed.append(tag)
    return frozenset(allowed)


class AuthorizedSafeLoader(SafeLoader):
    """Base class for per-load authorized loaders.

    Do not instantiate directly; use :func:`authorized_loader`,
    :func:`authorized_load` or :func:`authorized_load_all`.
    """

    #: Tags authorized for this load (besides the standard safe tags).
    authorized_tags = frozenset()


def authorized_loader(allowed_tags=()):
    """Create a SafeLoader subclass with a frozen authorization snapshot.

    ``allowed_tags`` is an iterable of custom tag names (e.g. ``'!Point'``)
    whose constructors -- as registered on ``SafeLoader`` *right now* --
    are authorized for this load.  The returned loader class:

    * keeps the standard safe tags working,
    * executes only the authorized custom constructors,
    * rejects any other custom tag with :class:`UnauthorizedTagError`
      (carrying line/column) before its constructor runs,
    * is unaffected by constructors registered later on ``SafeLoader``.

    Authorization can never enable ``python/*`` object construction;
    passing such a tag raises ``ValueError``.
    """
    allowed = _validate_allowed_tags(allowed_tags)
    registry = SafeLoader.yaml_constructors
    constructors = _standard_safe_constructors()
    for tag in sorted(allowed):
        constructor = registry.get(tag)
        if constructor is None:
            raise ValueError(
                    "no constructor registered on SafeLoader for "
                    "authorized tag %r" % tag)
        constructors[tag] = constructor
    # Any other tag is rejected before construction, with line/column.
    constructors[None] = _reject_unauthorized
    multi_constructors = _standard_safe_multi_constructors()
    namespace = {
        'yaml_constructors': constructors,
        'yaml_multi_constructors': multi_constructors,
        'authorized_tags': allowed,
        '__doc__': 'AuthorizedSafeLoader snapshot for tags: %s'
                   % (', '.join(sorted(allowed)) or '<none>'),
    }
    return type('AuthorizedSafeLoader', (AuthorizedSafeLoader,), namespace)


def authorized_load(stream, allowed_tags=()):
    """Parse the first YAML document in a stream with a per-load
    authorization list of custom tags, and produce the corresponding
    Python object.

    See :func:`authorized_loader` for the authorization semantics.
    """
    loader = authorized_loader(allowed_tags)(stream)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def authorized_load_all(stream, allowed_tags=()):
    """Parse all YAML documents in a stream with a single per-load
    authorization snapshot shared by every document, and produce the
    corresponding Python objects.

    The authorization snapshot is frozen when this function is called;
    tags registered afterwards -- even while earlier documents of this
    very stream are being constructed -- are not authorized.
    """
    # Freeze the snapshot eagerly, at call time, not at first iteration.
    Loader = authorized_loader(allowed_tags)

    def generate():
        loader = Loader(stream)
        try:
            while loader.check_data():
                yield loader.get_data()
        finally:
            loader.dispose()

    return generate()
