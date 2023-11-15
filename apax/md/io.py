import logging
from pathlib import Path
import numpy as np
import znh5md
from ase import Atoms
import h5py
from ase.calculators.singlepoint import SinglePointCalculator
from jax_md.space import transform

from apax.md.sim_utils import System

log = logging.getLogger(__name__)


class TrajHandler:
    def step(self, state_and_energy, transform):
        pass

    def write(self, x=None, transform=None):
        pass

    def close(self):
        pass

    def reset_buffer(self):
        pass

    def atoms_from_state(self, state, energy, nbr_kwargs):
        if "box" in nbr_kwargs.keys():
            box = nbr_kwargs["box"]
        else:
            box = self.box

        if self.fractional:
            positions = transform(box, state.position)
        else:
            positions = state.position

        positions = np.asarray(positions)
        momenta = np.asarray(state.momentum)
        forces = np.asarray(state.force)

        atoms = Atoms(self.atomic_numbers, positions, momenta=momenta, cell=box)
        atoms.cell = atoms.cell.T
        atoms.pbc = np.diag(atoms.cell.array) > 1e-7
        atoms.calc = SinglePointCalculator(atoms, energy=float(energy), forces=forces)
        return atoms


class H5TrajHandler(TrajHandler):
    def __init__(self, system: System, sampling_rate: int, traj_path: Path, time_step= 0.5) -> None:
        self.atomic_numbers = system.atomic_numbers
        self.box = system.box
        self.fractional = np.any(self.box < 1e-6)
        self.sampling_rate = sampling_rate
        self.traj_path = traj_path
        self.db = znh5md.io.DataWriter(self.traj_path)
        if not self.traj_path.is_file():
            log.info(f"Initializing new trajectory file at {self.traj_path}")
            self.db.initialize_database_groups()
        self.time_step = time_step

        self.step_counter = 0
        self.buffer = []

    def reset_buffer(self):
        self.buffer = []

    def step(self, state, transform):
        state, energy, nbr_kwargs = state

        if self.step_counter % self.sampling_rate == 0: # use modulo
            new_atoms = self.atoms_from_state(state, energy, nbr_kwargs)
            self.buffer.append(new_atoms)
        self.step_counter += 1

    def write(self, x=None, transform=None):
        if len(self.buffer) > 0:
            reader = znh5md.io.AtomsReader(
                self.buffer,
                step=self.time_step,
                time=self.time_step * self.step_counter,
                # TODO frames per chunk?
            )
            self.db.add(reader)
            self.reset_buffer()


class DSTruncator:
    def __init__(self, length):
        self.length = length
        self.node_names = []
    
    def __call__(self, name, node):
        if isinstance(node, h5py.Dataset):
            if len(node.shape) > 1 or name.endswith("energy/value"):
                self.node_names.append(name)

    def truncate(self, ds):
        for name in self.node_names:
            truncated_data = ds[name][:self.length]
            del ds[name]
            ds.create_dataset(name,data=truncated_data)


def truncate_trajectory_to_checkpoint(traj_path, length):
    truncator = DSTruncator(length=length)
    with h5py.File(traj_path, 'r+') as ds:
        ds.visititems(truncator)
        truncator.truncate(ds)
