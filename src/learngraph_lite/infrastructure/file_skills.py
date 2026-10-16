"""Load bounded, declarative SKILL.md files into an immutable startup snapshot."""

from __future__ import annotations

import re
import stat
from pathlib import Path
from types import MappingProxyType

import yaml

from learngraph_lite.application.skills import MAX_SKILL_BODY_BYTES, SKILL_MODES, SkillDefinition


MAX_SKILL_FILE_BYTES = 16384
MAX_CATALOG_SKILLS = 32
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _checked_stat(path: Path, root: Path | None = None):
    info = path.lstat()
    # Windows junctions (and other reparse points) must not be followed either.
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("skill catalog links are not allowed")
    if root is not None and not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("skill catalog entry escapes its root")
    return info


def _parse_skill(raw: bytes, directory_name: str) -> SkillDefinition:
    try:
        lines = raw.decode("utf-8-sig", errors="strict").splitlines(keepends=True)
    except UnicodeDecodeError:
        raise ValueError("skill file must be UTF-8") from None
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("skill file requires YAML frontmatter")
    end = next((index for index in range(1, len(lines)) if lines[index].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValueError("skill frontmatter is not closed")
    try:
        header = yaml.safe_load("".join(lines[1:end]))
    except (yaml.YAMLError, RecursionError):
        # YAML diagnostics include source excerpts; never propagate them.
        raise ValueError("skill frontmatter is invalid YAML") from None
    if not isinstance(header, dict):
        raise ValueError("skill frontmatter must be a mapping")
    name = header.get("name")
    if not isinstance(name, str) or len(name) > 64 or _SKILL_NAME.fullmatch(name) is None or name != directory_name:
        raise ValueError("skill name must be a valid directory-matching identifier")
    description = header.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        raise ValueError("skill description must be nonempty and at most 1024 characters")
    instructions = "".join(lines[end + 1:])
    if not instructions.strip() or len(instructions.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise ValueError("skill body must be nonempty and within its byte limit")
    modes = SKILL_MODES
    if "metadata" in header:
        metadata = header["metadata"]
        if not isinstance(metadata, dict):
            raise ValueError("skill metadata must be a mapping")
        if "learngraph" in metadata:
            learngraph = metadata["learngraph"]
            if not isinstance(learngraph, dict):
                raise ValueError("skill learngraph metadata must be a mapping")
            if "modes" in learngraph:
                selected = learngraph["modes"]
                if (not isinstance(selected, list) or not selected
                        or any(not isinstance(mode, str) or mode not in SKILL_MODES for mode in selected)
                        or len(set(selected)) != len(selected)):
                    raise ValueError("skill modes must be a nonempty unique list of supported modes")
                modes = tuple(selected)
    # Compatibility metadata (including allowed-tools) never grants capabilities.
    return SkillDefinition(id=name, description=description, instructions=instructions, modes=tuple(modes))


class FileSkillCatalog:
    """A missing root is an empty catalog; existing invalid entries fail startup.

    Only direct child directories with SKILL.md are candidates. No other files,
    nested skills, scripts, or metadata capabilities are loaded or executed.
    """

    def __init__(self, root: Path):
        try:
            definitions = self._scan(root)
        except (OSError, RuntimeError):
            raise ValueError("skill catalog cannot be read safely") from None
        self._skills = tuple(definitions)
        self._by_id = MappingProxyType({skill.id: skill for skill in self._skills})

    @staticmethod
    def _scan(root: Path) -> list[SkillDefinition]:
        try:
            info = _checked_stat(root)
        except FileNotFoundError:
            return []
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("skill catalog root must be a directory")
        resolved_root = root.resolve(strict=True)
        definitions = []
        for directory in sorted(root.iterdir(), key=lambda entry: entry.name):
            directory_info = _checked_stat(directory, resolved_root)
            if not stat.S_ISDIR(directory_info.st_mode):
                continue
            skill_file = directory / "SKILL.md"
            try:
                file_info = _checked_stat(skill_file, resolved_root)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(file_info.st_mode):
                raise ValueError("skill file must be a regular file")
            if file_info.st_size > MAX_SKILL_FILE_BYTES:
                raise ValueError("skill file exceeds its byte limit")
            with skill_file.open("rb") as stream:
                raw = stream.read(MAX_SKILL_FILE_BYTES + 1)
            if len(raw) > MAX_SKILL_FILE_BYTES:
                raise ValueError("skill file exceeds its byte limit")
            definitions.append(_parse_skill(raw, directory.name))
            if len(definitions) > MAX_CATALOG_SKILLS:
                raise ValueError("skill catalog exceeds its skill limit")
        return definitions

    def list_skills(self) -> tuple[SkillDefinition, ...]:
        return self._skills

    def read_skill(self, skill_id: str) -> SkillDefinition:
        return self._by_id[skill_id]
