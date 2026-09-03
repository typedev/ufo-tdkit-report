"""Tests for the repo registry: nested entries, path lookup, legacy migration, pruning."""

import json

import pytest

from ufo_tdkit_report import registry


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))


def _repo(tmp_path, name):
    path = tmp_path / name
    (path / ".git").mkdir(parents=True)
    return path


def test_add_stores_an_object_entry_with_overrides(tmp_path):
    repo = _repo(tmp_path, "MyFont")
    stored = registry.add("myfont", str(repo), account="acme", language="Spanish")
    assert stored == str(repo.resolve())
    assert registry.entry("myfont") == {
        "path": str(repo.resolve()),
        "account": "acme",
        "language": "Spanish",
    }
    assert registry.resolve("myfont") == str(repo.resolve())


def test_re_registering_keeps_existing_overrides_and_can_clear_one(tmp_path):
    repo = _repo(tmp_path, "MyFont")
    registry.add("myfont", str(repo), account="acme", language="Spanish")
    registry.add("myfont", str(repo))  # a plain re-register must not wipe the binding
    assert registry.entry("myfont")["account"] == "acme"
    registry.add("myfont", str(repo), language=None)  # explicit None clears
    assert "language" not in registry.entry("myfont")


def test_unknown_override_is_rejected(tmp_path):
    repo = _repo(tmp_path, "MyFont")
    with pytest.raises(ValueError, match="unknown repo override"):
        registry.add("myfont", str(repo), api_key="sk-nope")


def test_the_legacy_flat_format_is_read_transparently(tmp_path):
    # Pre-0.2 registries stored name -> path as a bare string.
    config = tmp_path / "cfg" / "ufo-tdkit-report"
    config.mkdir(parents=True)
    repo = _repo(tmp_path, "OldFont")
    (config / "repos.json").write_text(json.dumps({"oldfont": str(repo)}))
    assert registry.resolve("oldfont") == str(repo)
    assert registry.entry("oldfont") == {"path": str(repo)}
    # And is rewritten in the object form on the next write.
    registry.add("oldfont", str(repo), account="acme")
    stored = json.loads((config / "repos.json").read_text())
    assert stored["oldfont"] == {"path": str(repo.resolve()), "account": "acme"}


def test_lookup_by_path_and_by_name_is_case_insensitive(tmp_path):
    repo = _repo(tmp_path, "MyFont")
    registry.add("MyFont", str(repo), account="acme")
    assert registry.resolve("myfont") == str(repo.resolve())
    assert registry.entry_for_path(str(repo))["account"] == "acme"
    assert registry.name_for_path(str(repo)) == "MyFont"
    assert registry.entry_for_path(str(tmp_path / "nowhere")) is None


def test_a_path_inside_a_repo_finds_it(tmp_path):
    """`git -C <anything inside>` works, so the binding lookup must too.

    A consumer handing over a subdirectory used to fall through to the default account
    and narrate with the wrong provider and key, silently.
    """
    repo = _repo(tmp_path, "MyFont")
    (repo / "sources" / "MyFont.ufo" / "glyphs").mkdir(parents=True)
    registry.add("myfont", str(repo), account="work")

    for inside in (repo, repo / "sources", repo / "sources" / "MyFont.ufo" / "glyphs"):
        assert registry.entry_for_path(str(inside))["account"] == "work", inside
        assert registry.name_for_path(str(inside)) == "myfont"
    # A sibling that merely shares a prefix is not inside it.
    sibling = _repo(tmp_path, "MyFontExtra")
    assert registry.entry_for_path(str(sibling)) is None


def test_the_deepest_registered_ancestor_wins(tmp_path):
    outer = _repo(tmp_path, "Outer")
    inner = outer / "vendor" / "Inner"
    (inner / ".git").mkdir(parents=True)
    registry.add("outer", str(outer), account="a")
    registry.add("inner", str(inner), account="b")
    assert registry.entry_for_path(str(inner))["account"] == "b"
    assert registry.entry_for_path(str(inner / "sources"))["account"] == "b"
    assert registry.entry_for_path(str(outer / "sources"))["account"] == "a"


def test_remove_and_prune_report_what_went(tmp_path):
    live = _repo(tmp_path, "Live")
    dead = _repo(tmp_path, "Dead")
    registry.add("live", str(live))
    registry.add("dead", str(dead))
    from conftest import rmtree

    rmtree(dead)
    assert registry.stale() == [("dead", str(dead.resolve()))]
    assert registry.prune() == [("dead", str(dead.resolve()))]
    assert registry.stale() == []
    assert registry.resolve("live") == str(live.resolve())
    assert registry.remove("LIVE") is True  # case-insensitive
    assert registry.remove("gone") is False


def test_a_corrupt_registry_degrades_instead_of_raising(tmp_path):
    config = tmp_path / "cfg" / "ufo-tdkit-report"
    config.mkdir(parents=True)
    (config / "repos.json").write_text("{not json")
    assert registry.load() == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
