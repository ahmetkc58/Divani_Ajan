from scripts.run_acceptance_metrics import percentile


def test_percentile_uses_deterministic_nearest_rank() -> None:
    values = [float(value) for value in range(1, 21)]

    assert percentile(values, 0.50) == 10.0
    assert percentile(values, 0.95) == 19.0
    assert percentile([], 0.95) == 0.0
