from burn_subs.cli import _expand_inputs


def test_expand_inputs_keeps_unique_order(tmp_path) -> None:
    a = tmp_path / "a.mkv"
    b = tmp_path / "b.mkv"
    a.write_text("x")
    b.write_text("y")

    out = _expand_inputs([str(a), str(a), str(b)])
    assert out == [str(a), str(b)]

