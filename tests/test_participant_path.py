from training_tools import anforderungskatalog_laden


def test_participant_path():
    assert len(anforderungskatalog_laden("A-100")["requirements"]) == 6
