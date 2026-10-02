"""`operonx-run` loads `./.env` before the application is imported.

On a machine that selects `local.env`, those values would otherwise win
(`override=False`) and a local-stack run would talk to the cluster — the
mix `src/core/_bootstrap.py` exists to prevent. `drop_preloaded` undoes it.
"""
from src.core._bootstrap import drop_preloaded


def test_a_key_the_other_file_set_takes_the_selected_files_value():
    env = {"PG_DSN": "cluster"}
    drop_preloaded(env, selected={"PG_DSN": "local"}, other={"PG_DSN": "cluster"})
    assert env == {"PG_DSN": "local"}


def test_a_key_only_the_other_file_has_is_dropped():
    env = {"S3_BUCKET": "prod-bucket"}
    drop_preloaded(env, selected={}, other={"S3_BUCKET": "prod-bucket"})
    assert env == {}


def test_a_shell_variable_is_left_alone():
    env = {"PG_DSN": "from-my-shell"}
    drop_preloaded(env, selected={"PG_DSN": "local"}, other={"PG_DSN": "cluster"})
    assert env == {"PG_DSN": "from-my-shell"}


def test_keys_nobody_preloaded_are_untouched():
    env = {"PATH": "x"}
    drop_preloaded(env, selected={"PG_DSN": "local"}, other={"PG_DSN": "cluster"})
    assert env == {"PATH": "x"}
