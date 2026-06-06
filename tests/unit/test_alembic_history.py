from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_history_has_single_head_and_loads():
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()

    assert len(heads) == 1
