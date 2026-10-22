"""esteward: the self-maintenance engine of EDamLabs projects.

Declared `__init__` exception (tax-py-naming): the package's beartype import hook, nothing else.
"""

from beartype.claw import beartype_this_package

beartype_this_package()
