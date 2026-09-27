from training_tools import anforderungskatalog_laden


def test_catalogue_count_in_pr_ci():
    assert len(anforderungskatalog_laden('A-100')['requirements']) == 6
