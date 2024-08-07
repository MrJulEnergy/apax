from apax.layers.descriptor.gaussian_moment_descriptor import GaussianMomentDescriptor
from apax.layers.descriptor.equiv_mp import EquivMPRepresentation

try:
    from apax.layers.descriptor.so3krates import So3kratesRepresentation
except ImportError:
    So3kratesRepresentation = None

__all__ = ["GaussianMomentDescriptor", "EquivMPRepresentation", "So3kratesRepresentation"]
