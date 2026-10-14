import os
import shutil
import tempfile

from octt import cli
from octt.io import load, save
from octt.demo import demo

d = tempfile.mkdtemp()
f = os.path.join(d, "t.json")
save(demo(), f)


def test_check_set_solve_pdf_convert():
    assert cli.run(["check", f]) == 0
    cli.run(["set", f, "teacher_days=3", "w.student_gaps=2"])
    doc = load(f)
    assert doc.params["teacher_days"] == 3 and doc.weights["student_gaps"] == 2
    assert cli.run(["solve", f, "--scratch", "--time", "5"]) == 0
    assert len(load(f).placements) == 8
    cli.run(["pdf", f, os.path.join(d, "o.pdf"), "--kind", "teacher"])
    assert os.path.getsize(os.path.join(d, "o.pdf")) > 1000
    for ext in ("html", "xlsx"):
        cli.run(["export", f, os.path.join(d, "o." + ext), "--kind", "class"])
    assert "<table" in open(os.path.join(d, "o.html"), encoding="utf-8").read()
    import zipfile
    from xml.dom import minidom
    with zipfile.ZipFile(os.path.join(d, "o.xlsx")) as z:  # every part is well-formed XML and the grid holds lesson text
        for n in z.namelist():
            minidom.parseString(z.read(n))
        assert b"Mon" in z.read("xl/worksheets/sheet1.xml")
    for ext in ("pdf", "html", "xlsx"):  # custom style must not break any writer
        o = os.path.join(d, "s." + ext)
        cli.run(["export", f, o, "--font", "Serif", "--size", "12", "--header", "#cce5ff", "--no-colors", "--no-borders"])
        assert os.path.getsize(o) > 500
    assert "#cce5ff" in open(os.path.join(d, "s.html"), encoding="utf-8").read()
    with zipfile.ZipFile(os.path.join(d, "s.xlsx")) as z:
        assert b"CCE5FF" in z.read("xl/styles.xml") and b'name val="Serif"' in z.read("xl/styles.xml")
        minidom.parseString(z.read("xl/styles.xml"))
    cli.run(["convert", f, os.path.join(d, "c.json")])
    shutil.rmtree(d)


def test_bad_setting_exits():
    own = os.path.join(tempfile.mkdtemp(), "t.json")
    save(demo(), own)
    try:
        cli.run(["set", own, "nope=1"])
    except SystemExit as e:
        assert "bad setting 'nope=1'" in str(e.code)
        return
    raise AssertionError


def test_wrong_shaped_json_exits_with_a_message():
    bad = os.path.join(tempfile.mkdtemp(), "bad.json")
    with open(bad, "w") as fh:
        fh.write('{"institution": "x"}')
    try:
        cli.run(["info", bad])
    except SystemExit as e:
        assert "cannot open" in str(e.code) and "year" in str(e.code)
        return
    raise AssertionError

if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
    os._exit(0)
