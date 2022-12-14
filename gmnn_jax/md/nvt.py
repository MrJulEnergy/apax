import logging
import os
import time
from functools import partial

import jax
import jax.numpy as jnp
import yaml
from ase import Atoms, units
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import read
from ase.io.trajectory import TrajectoryWriter
from flax.training import checkpoints
from jax_md import simulate, space

from gmnn_jax.config import Config, MDConfig
from gmnn_jax.model.gmnn import get_md_model
from gmnn_jax.md.md_checkpoint import load_md_state, look_for_checkpoints

log = logging.getLogger(__name__)


def run_nvt(
    R,
    atomic_numbers,
    masses,
    box,
    energy_fn,
    neighbor_fn,
    shift_fn,
    dt,
    temperature,
    n_steps,
    n_inner,
    extra_capacity,
    rng_key,
    restart=True,
    sim_dir=".",
    traj_name="nvt.traj",
):
    sim_time = dt * n_steps
    K_B = 8.617e-5
    dt = dt * units.fs
    kT = K_B * temperature
    step = 0
    checkpoint_interval = 10 # TODO will be supplied in the future

    log.info("initializing simulation")
    neighbor = neighbor_fn.allocate(R, extra_capacity=extra_capacity)
    init_fn, apply_fn = simulate.nvt_nose_hoover(energy_fn, shift_fn, dt, kT)
    # async_manager = checkpoints.AsyncManager()
    restart = False # TODO needs to be implemented
    if restart:
        log.info("looking for checkpoints")
        ckpts_exist = look_for_checkpoints(sim_dir)
        if ckpts_exist:
            log.info("loading previous md state")
            state, step = load_md_state(sim_dir)
        else:
            state = init_fn(rng_key, R, masses, neighbor=neighbor)    
    else:
        state = init_fn(rng_key, R, masses, neighbor=neighbor)
    # TODO capability to restart md.
    # May require serializing the state instead of ASE Atoms trajectory + conversion
    # Maybe we can use flax checkpoints for that?
    # -> can't serialize NHState and chain for some reason?

    @jax.jit
    def sim(state, neighbor):
        def body_fn(i, state):
            state, neighbor = state
            neighbor = neighbor.update(state.position)
            state = apply_fn(state, neighbor=neighbor)
            return state, neighbor

        return jax.lax.fori_loop(0, n_inner, body_fn, (state, neighbor))

    traj_path = os.path.join(sim_dir, traj_name)
    traj = TrajectoryWriter(traj_path, mode="w")
    n_outer = int(n_steps // n_inner)

    start = time.time()
    # TODO: log starting time when epoch loaded
    log.info("running nvt for %.1f fs", sim_time)
    while step < n_outer:
        new_state, neighbor = sim(state, neighbor)
        if neighbor.did_buffer_overflow:
            log.info("step %d: neighbor list overflowed, reallocating.", step)
            neighbor = neighbor_fn.allocate(state.position)
        else:
            state = new_state
            step += 1
            new_atoms = Atoms(atomic_numbers, state.position, cell=box)
            new_atoms.calc = SinglePointCalculator(new_atoms, forces=state.force)
            traj.write(new_atoms)

            if step % checkpoint_interval == 0:
                log.info("saving checkpoint at step: %d", step)
                log.info("checkpoints not yet implemented")
    traj.close()

    end = time.time()
    elapsed_time = end - start
    log.info("simulation finished after elapsed time: %.2f s", elapsed_time)


def md_setup(model_config, md_config):

    log.info("reading structure")
    atoms = read(md_config.initial_structure)

    R = jnp.asarray(atoms.positions)
    atomic_numbers = jnp.asarray(atoms.numbers)
    masses = jnp.asarray(atoms.get_masses())
    box = jnp.asarray(atoms.get_cell().lengths())

    log.info("initializing model")
    displacement_fn, shift_fn = space.periodic(box)

    neighbor_fn, _, model = get_md_model(
        atomic_numbers=atomic_numbers,
        displacement_fn=displacement_fn,
        displacement=displacement_fn,
        box_size=box,
        dr_threshold=md_config.dr_threshold,
        **model_config.model.dict()
    )

    os.makedirs(md_config.sim_dir, exist_ok=True)

    log.info("loading model parameters")
    raw_restored = checkpoints.restore_checkpoint(
        model_config.data.model_path, target=None, step=None
    )
    params = jax.tree_map(jnp.asarray, raw_restored["model"]["params"])
    energy_fn = partial(model, params)

    return R, atomic_numbers, masses, box, energy_fn, neighbor_fn, shift_fn


def run_md(model_config, md_config):
    log.info("loading configs for md")
    if isinstance(model_config, str):
        with open(model_config, "r") as stream:
            model_config = yaml.safe_load(stream)

    if isinstance(md_config, str):
        with open(md_config, "r") as stream:
            md_config = yaml.safe_load(stream)

    model_config = Config.parse_obj(model_config)
    md_config = MDConfig.parse_obj(md_config)

    rng_key = jax.random.PRNGKey(md_config.seed)
    md_init_rng_key, rng_key = jax.random.split(rng_key, 2)

    R, atomic_numbers, masses, box, energy_fn, neighbor_fn, shift_fn = md_setup(model_config, md_config)
    
    run_nvt(
        R=R,
        atomic_numbers=atomic_numbers,
        masses=masses,
        box=box,
        energy_fn=energy_fn,
        neighbor_fn=neighbor_fn,
        shift_fn=shift_fn,
        dt=md_config.dt,
        temperature=md_config.temperature,
        n_steps=md_config.n_steps,
        n_inner=md_config.n_inner,
        extra_capacity=md_config.extra_capacity,
        rng_key=md_init_rng_key,
        restart=md_config.restart,
        sim_dir=md_config.sim_dir,
        traj_name=md_config.traj_name,
    )
