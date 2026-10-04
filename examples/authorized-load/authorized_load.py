"""Example: per-load authorized tag loading with yaml.authorized_load*.

Only the custom tags on the explicit authorization list may execute for
this load; everything else (including tags registered later by other
modules, and any python/* tag) is rejected with line/column information.
The global SafeLoader table and the default yaml.safe_load* entry points
are not affected.

Run from the repository root with the in-tree package:

    PYTHONPATH=lib python examples/authorized-load/authorized_load.py
"""

import yaml


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __repr__(self):
        return f"Point(x={self.x}, y={self.y})"


def point_constructor(loader, node):
    x, y = loader.construct_sequence(node)
    return Point(x, y)


secret_calls = 0


def secret_constructor(loader, node):
    global secret_calls
    secret_calls += 1
    return loader.construct_scalar(node)


# Custom constructors are registered on SafeLoader as usual ...
yaml.add_constructor('!Point', point_constructor, Loader=yaml.SafeLoader)
yaml.add_constructor('!Secret', secret_constructor, Loader=yaml.SafeLoader)

# ... but each load decides which of them it authorizes.  The constructor
# table is frozen into a snapshot when the loader is created.
stream = """\
start: &p !Point [1, 2]
again: *p
---
end: !Point [3, 4]
"""

# Both documents of the stream share the same authorization snapshot.
docs = list(yaml.authorized_load_all(stream, allowed_tags=['!Point']))
print("authorized docs:", docs)
assert docs[0]['again'] is docs[0]['start']  # aliases keep working

# !Secret is registered globally, but it is NOT on this load's
# authorization list, so it is rejected before its constructor runs.
try:
    yaml.authorized_load("leak: !Secret s3cr3t\n", allowed_tags=['!Point'])
except yaml.UnauthorizedTagError as exc:
    print("rejected with line/column:")
    print(exc)
assert secret_calls == 0, "the Secret constructor must never run"

# A tag registered *after* the snapshot was frozen is not authorized,
# even if the load happens later.
yaml.add_constructor('!Late', lambda loader, node: loader.construct_scalar(node),
                     Loader=yaml.SafeLoader)
try:
    yaml.authorized_load("!Late nope\n", allowed_tags=['!Point'])
except yaml.UnauthorizedTagError as exc:
    print("late registration rejected:", exc.problem)

# Authorization can never enable python object construction.
try:
    yaml.authorized_loader(['tag:yaml.org,2002:python/object:os.system'])
except ValueError as exc:
    print("python authorization refused:", exc)

# The default entry points are unchanged: safe_load uses the global table.
print("safe_load still works:", yaml.safe_load("a: 1"))
