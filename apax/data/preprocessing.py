import collections
import itertools
import logging
from typing import Callable

import jax
import jax.numpy as jnp
import numpy as np
from ase import Atoms
from matscipy.neighbours import neighbour_list
from tqdm import trange

from apax.utils.jax_md_reduced import partition, space

log = logging.getLogger(__name__)


def dataset_neighborlist(
    positions: list[np.array],
    box: list[np.array],
    r_max: float,
    atoms_list,
    disable_pbar: bool = False,
) -> list[int]:
    """Calculates the neighbor list of all systems within positions using
    a jax_md.partition.NeighborFn.

    Parameters
    ----------
    neighbor_fn :
        Neighbor list function (jax_md.partition.NeighborFn).
    positions :
        Cartesian coordinates of all atoms in all structures.

    Returns
    -------
    idxs :
        Neighbor list of all structures.
    """
    log.info("Precomputing neighborlists")
    # The JaxMD NL throws an error if np arrays are passed to it in the CPU version
    idx_list = []
    offset_list = []

    nl_pbar = trange(
        len(positions),
        desc="Precomputing NL",
        ncols=100,
        mininterval=0.25,
        disable=disable_pbar,
        leave=True,
    )
    for i, position in enumerate(positions):
        if np.all(box[i] < 1e-6):
            cell, cell_origin = get_shrink_wrapped_cell(position)
            idxs_i, idxs_j = neighbour_list(
                "ij",
                positions=position,
                cutoff=r_max,
                cell=cell,
                cell_origin=cell_origin,
                pbc=[False, False, False],
            )

            neighbor_idxs = np.array([idxs_i, idxs_j], dtype=np.int32)

            n_neighbors = neighbor_idxs.shape[1]
            offsets = np.full([n_neighbors, 3], 0)
        else:
            idxs_i, idxs_j, offsets = neighbour_list(
                "ijS",
                atoms_list[i],
                r_max,
            )
            offsets = np.matmul(offsets, box[i])
            neighbor_idxs = np.array([idxs_i, idxs_j], dtype=np.int32)

        offset_list.append(offsets)
        idx_list.append(neighbor_idxs)
        nl_pbar.update()
    nl_pbar.close()

    return idx_list, offset_list


def get_shrink_wrapped_cell(positions):
    rmin = np.min(positions, axis=0)
    rmax = np.max(positions, axis=0)
    cell_origin = rmin
    cell = np.diag(rmax - rmin)
    for idx in range(3):
        if cell[idx, idx] < 10e-1:
            cell[idx, idx] = 1.0

    cell[np.diag_indices_from(cell)] += 1

    return cell, cell_origin


def prefetch_to_single_device(iterator, size: int):
    """
    inspired by
    https://flax.readthedocs.io/en/latest/_modules/flax/jax_utils.html#prefetch_to_device
    except it does not shard the data.
    """
    queue = collections.deque()

    def _prefetch(x):
        return jnp.asarray(x)

    def enqueue(n):
        for data in itertools.islice(iterator, n):
            queue.append(jax.tree_util.tree_map(_prefetch, data))

    enqueue(size)
    while queue:
        yield queue.popleft()
        enqueue(1)
