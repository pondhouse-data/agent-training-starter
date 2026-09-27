from training_tools import anforderungskatalog_laden


def test_intentional_red_ci_run():
    assert len(anforderungskatalog_laden('A-100')['requirements']) == 7  # absichtlich falsch
