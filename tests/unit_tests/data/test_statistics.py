import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator

from apax.data.statistics import per_element_regression


def test_energy_per_element():
    pos = [0.0, 0.0, 0.0]
    atoms1 = Atoms("H2O", positions=[pos, pos, pos])
    atoms2 = Atoms("CH4", positions=[pos, pos, pos, pos, pos])
    atoms3 = Atoms("N2", positions=[pos, pos])

    dummy_energies = np.array([0, 20.0, 0, 0, 0, 0, 50.0, 100.0, 70.0])

    atoms_list = [atoms1, atoms2, atoms3]
    energies = []
    for atoms in atoms_list:
        energy = np.sum(dummy_energies[atoms.numbers])
        energies.append(energy)
        atoms.calc = SinglePointCalculator(atoms, energy=energy)

    ds_stats = per_element_regression(atoms_list, 0.0)
    elemental_shift = ds_stats.elemental_shift
    regression_energies = []
    for atoms in atoms_list:
        energy = np.sum(elemental_shift[atoms.numbers])
        regression_energies.append(energy)

    assert np.allclose(energies, regression_energies, atol=1e-4)
