import jax.numpy as jnp

from gmnn_jax.train.metrics import cosine_sim, initialize_metrics


def test_cosine_sim():
    prediction = {
        "forces": jnp.array(
            [
                [
                    [0.5, 0.0, 0.0],
                    [0.5, 0.0, 0.0],
                ]
            ]
        )
    }

    label = {
        "forces": jnp.array(
            [
                [
                    [0.0, 0.5, 0.0],
                    [0.5, 0.0, 0.0],
                ]
            ]
        )
    }

    angle_error = cosine_sim(label, prediction, "forces")
    assert angle_error.shape == ()
    ref = 0.5
    assert abs(angle_error - ref) < 1e-6


def test_initialize_metrics_collection():
    prediction = {
        "energy": jnp.array([1.0, 1.0]),
        "forces": jnp.array(
            [
                [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            ]
        ),
    }

    label = {
        "energy": jnp.array([1.0, 2.0]),
        "forces": jnp.array(
            [
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                [[1.0, 0.0, 0.0], [2.0, 1.0, 0.0]],
            ]
        ),
    }
    keys = ["energy", "energy", "forces", "forces"]
    reductions = ["mae", "rmse", "mae", "mse"]
    Metrics = initialize_metrics(keys, reductions)
    batch_metrics = Metrics.single_from_model_output(label=label, prediction=prediction)

    epoch_metrics = batch_metrics.compute()
    # print(epoch_metrics)
    assert abs(epoch_metrics["energy_mae"] - 0.5) < 1e-6
    assert abs(epoch_metrics["energy_rmse"] - jnp.sqrt(0.5)) < 1e-6
    assert abs(epoch_metrics["forces_mae"] - 1 / 3) < 1e-6
    assert abs(epoch_metrics["forces_mse"] - 1 / 3) < 1e-6
