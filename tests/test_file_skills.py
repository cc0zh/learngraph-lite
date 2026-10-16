from __future__ import annotations

import hashlib
import inspect
import os
import subprocess
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

from learngraph_lite.application.skills import MAX_SKILL_BODY_BYTES, SKILL_MODES
from learngraph_lite.infrastructure.file_skills import MAX_CATALOG_SKILLS, MAX_SKILL_FILE_BYTES, FileSkillCatalog


def skill_text(name="demo", description="解释当前学习概念", body="逐步讲解。\n", extra=""):
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\n{body}"


def write_skill(root, name="demo", text=None):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_bytes((text if text is not None else skill_text(name)).encode("utf-8"))
    return path


def expect_invalid(root, text=None):
    try:
        FileSkillCatalog(root)
    except ValueError as exc:
        message = str(exc)
        assert message and str(root.resolve()) not in message
        if text:
            assert text not in message
        assert exc.__context__ is None or exc.__suppress_context__, "unsafe nested exceptions must not escape"
        return message
    raise AssertionError("expected invalid skill catalog")


def try_symlink(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        print("SKIP: symbolic links are unavailable on this platform")
        return False
    return True


def test_builtin_skill_format_hashes_and_modes():
    root = Path(__file__).resolve().parents[1] / "src" / "learngraph_lite" / "skills"
    catalog = FileSkillCatalog(root)
    assert tuple(skill.id for skill in catalog.list_skills()) == ("concept-teaching", "goal-planning")
    assert catalog.read_skill("goal-planning").modes == ("planning",)
    assert catalog.read_skill("concept-teaching").modes == ("runner", "teaching", "explanation")
    for skill in catalog.list_skills():
        assert skill.description and skill.instructions.startswith("# ")
        assert len(skill.instructions.encode("utf-8")) <= MAX_SKILL_BODY_BYTES
        assert skill.content_hash == hashlib.sha256(skill.instructions.encode("utf-8")).hexdigest()
        assert not hasattr(skill, "path") and not hasattr(skill, "root")
        assert str(root) not in repr(skill)


def test_compatible_yaml_metadata_is_data_and_only_direct_children_are_loaded():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        extra = ('license: MIT\nallowed-tools: [shell, write_file]\n'
                 'metadata:\n  author: example\n  learngraph:\n    ignored: true\n'
                 '    modes: [teaching, runner]\n')
        write_skill(root, "z-last", skill_text("z-last", ">\n  第一行\n  第二行", extra=extra))
        write_skill(root, "a-first", skill_text("a-first", '"包含: 冒号 # 和井号"'))
        write_skill(root / "nested", "not-scanned")
        (root / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
        scripts = root / "a-first" / "scripts"
        scripts.mkdir()
        marker = root / "executed"
        (scripts / "run.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()", encoding="utf-8")
        catalog = FileSkillCatalog(root)
        assert tuple(skill.id for skill in catalog.list_skills()) == ("a-first", "z-last")
        assert catalog.read_skill("a-first").modes == tuple(SKILL_MODES)
        assert catalog.read_skill("z-last").modes == ("teaching", "runner")
        assert catalog.read_skill("z-last").description == "第一行 第二行\n"
        assert not marker.exists()


def test_missing_root_is_empty_but_existing_invalid_root_is_rejected():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "missing"
        assert FileSkillCatalog(root).list_skills() == ()
        assert not root.exists()
        root.write_text("not a directory", encoding="utf-8")
        expect_invalid(root)


def test_body_preserves_utf8_bom_crlf_and_hashes_exact_content():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        body = "\r\n  中文正文。\r\n"
        path = write_skill(root)
        path.write_bytes(b"\xef\xbb\xbf" + skill_text(body=body).replace("---\n", "---\r\n").encode("utf-8"))
        skill = FileSkillCatalog(root).read_skill("demo")
        assert skill.instructions == body
        assert skill.content_hash == hashlib.sha256(body.encode("utf-8")).hexdigest()


def test_catalog_and_definitions_are_immutable_startup_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = write_skill(root)
        catalog = FileSkillCatalog(root)
        listed = catalog.list_skills()
        assert isinstance(listed, tuple)
        skill = catalog.read_skill("demo")
        try:
            skill.instructions = "changed"
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError("skill definitions must be frozen")
        try:
            catalog._by_id["other"] = skill
        except TypeError:
            pass
        else:
            raise AssertionError("catalog lookup must be immutable")
        path.write_text("broken", encoding="utf-8")
        write_skill(root, "new-skill")
        path.unlink()
        assert catalog.list_skills() == listed and catalog.read_skill("demo") is skill
        assert skill.instructions == "逐步讲解。\n"


def test_unknown_skill_ids_are_key_errors_without_path_access():
    with tempfile.TemporaryDirectory() as directory:
        catalog = FileSkillCatalog(Path(directory))
        with patch.object(Path, "open", side_effect=AssertionError("lookup must not read files")):
            for skill_id in ("unknown", "../escape", "/absolute/path", ""):
                try:
                    catalog.read_skill(skill_id)
                except KeyError:
                    pass
                else:
                    raise AssertionError("unknown skill id must raise KeyError")


def test_malformed_frontmatter_and_utf8_errors_are_sanitized():
    texts = ("body only", "---\nname: demo\n", "---\n[]\n---\nbody", "---\n---\nbody",
             "---\nname: demo\n---\nbody", "---\ndescription: missing name\n---\nbody",
             "---\nname: demo\ndescription: [PRIVATE_INPUT\n---\nbody",
             skill_text(body=" \n\t"), skill_text(extra="metadata: []\n"),
             skill_text(extra="metadata:\n  learngraph: []\n"))
    for text in texts:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(root, text=text)
            assert "PRIVATE_INPUT" not in expect_invalid(root, text)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = write_skill(root)
        path.write_bytes(b"---\nname: demo\ndescription: \xff\n---\nbody")
        expect_invalid(root)


def test_python_yaml_tags_are_rejected_without_execution_or_content_leaks():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        marker = root / "PRIVATE_INPUT"
        payloads = (f'!!python/object/apply:pathlib.Path.touch [!!python/object/apply:pathlib.Path ["{marker.as_posix()}"]]',
                    '!!python/object:builtins.object {}', '!!python/name:os.system ""')
        for payload in payloads:
            write_skill(root, text=skill_text(extra=f"ignored: {payload}\n"))
            assert "PRIVATE_INPUT" not in expect_invalid(root)
            assert not marker.exists()


def test_name_and_description_constraints():
    invalid_names = ("Upper", "two--hyphens", "-leading", "trailing-", "under_score", "中文", "a" * 65, "12", "null")
    for name in invalid_names:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(root, name, skill_text(name=name))
            expect_invalid(root)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_skill(root, text=skill_text(name="wrong"))
        expect_invalid(root)
    for description in ('""', '" "', "[]", "null", "123", "长" * 1025):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(root, text=skill_text(description=description))
            expect_invalid(root)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        name = "a" * 64
        write_skill(root, name, skill_text(name, "长" * 1024))
        assert FileSkillCatalog(root).read_skill(name).description == "长" * 1024


def test_modes_must_be_unique_nonempty_lists_of_supported_strings():
    for modes in ("[]", "[planning, planning]", "[unknown]", "[planning, 1]", "planning", "null", "{}", "[[planning]]"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_skill(root, text=skill_text(extra=f"metadata:\n  learngraph:\n    modes: {modes}\n"))
            expect_invalid(root)


def test_body_and_entire_file_byte_limits():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        body = "教" * (MAX_SKILL_BODY_BYTES // 3) + "a" * (MAX_SKILL_BODY_BYTES % 3)
        path = write_skill(root, text=skill_text(body=body))
        assert len(FileSkillCatalog(root).read_skill("demo").instructions.encode("utf-8")) == MAX_SKILL_BODY_BYTES
        write_skill(root, text=skill_text(body=body + "a"))
        expect_invalid(root)
        text = skill_text(extra="# padding \n")
        padding = MAX_SKILL_FILE_BYTES - len(text.encode("utf-8"))
        write_skill(root, text=text.replace("# padding ", "# padding " + "x" * padding))
        assert path.stat().st_size == MAX_SKILL_FILE_BYTES
        assert FileSkillCatalog(root).read_skill("demo").id == "demo"
        path.write_bytes(path.read_bytes() + b"x")
        expect_invalid(root)


def test_catalog_has_at_most_32_valid_skills():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for index in range(MAX_CATALOG_SKILLS):
            write_skill(root, f"skill-{index:02d}")
        assert len(FileSkillCatalog(root).list_skills()) == MAX_CATALOG_SKILLS
        write_skill(root, "skill-overflow")
        expect_invalid(root)


def test_skill_file_must_be_regular_and_resolved_paths_cannot_escape_root():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "skills"
        path = write_skill(root)
        actual_resolve = Path.resolve
        for escaped in (path, path.parent):
            def resolve(candidate, *args, **kwargs):
                if candidate == escaped:
                    return Path(directory).resolve()
                return actual_resolve(candidate, *args, **kwargs)
            with patch.object(Path, "resolve", resolve):
                expect_invalid(root)
        with patch.object(Path, "open", side_effect=PermissionError(f"PRIVATE_INPUT {path.resolve()}")):
            assert "PRIVATE_INPUT" not in expect_invalid(root)
        path.unlink()
        path.mkdir()
        expect_invalid(root)


def test_symlink_directories_files_roots_and_dangling_links_are_rejected():
    for kind in ("directory", "internal-directory", "file", "internal-file", "root", "dangling"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "skills"
            root.mkdir()
            target = base / "outside"
            outside_file = write_skill(target)
            if kind == "root":
                root.rmdir()
                link, destination, is_directory = root, target, True
            elif kind in ("directory", "internal-directory", "dangling"):
                link = root / "linked"
                destination = target / "demo"
                if kind == "internal-directory":
                    destination = write_skill(root).parent
                elif kind == "dangling":
                    destination = base / "missing"
                is_directory = True
            else:
                destination = outside_file if kind == "file" else write_skill(root, "other")
                (root / "demo").mkdir()
                link, is_directory = root / "demo" / "SKILL.md", False
            if not try_symlink(link, destination, directory=is_directory):
                return
            expect_invalid(root)


def test_windows_junction_directory_is_rejected():
    if os.name != "nt":
        print("SKIP: Windows junction test requires Windows")
        return
    for kind in ("outside-directory", "internal-directory", "root", "file"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "skills"
            root.mkdir()
            target = write_skill(base / "outside").parent
            junction = root / "demo"
            if kind == "internal-directory":
                target = write_skill(root, "other").parent
            elif kind == "root":
                root.rmdir()
                junction = root
            elif kind == "file":
                junction.mkdir()
                junction /= "SKILL.md"
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True, check=False)
            if result.returncode != 0:
                print("SKIP: Windows junction creation is unavailable")
                return
            try:
                assert junction.is_junction()
                expect_invalid(root)
            finally:
                junction.rmdir()


if __name__ == "__main__":
    tests = sorted((name, function) for name, function in globals().copy().items()
                   if name.startswith("test_") and inspect.isfunction(function))
    for _, function in tests:
        function()
    print(f"{len(tests)} file skill tests passed")
