from pathlib import Path
from fundrec import config

def test_paths_are_under_repo_root():
    assert config.DATA_DIR.name == "data"
    assert config.DB_PATH.suffix == ".sqlite"
    assert isinstance(config.ROOT, Path)

def test_models_defined():
    assert config.EXTRACT_MODEL
    assert config.JUDGE_MODEL
