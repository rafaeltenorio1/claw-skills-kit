from typing import NamedTuple

from claw_skills_kit.models import Field, Template

_STANDARDS = "standards"
_ANSWERS = "client answers"

_STANDARDS_HEADER = ("key", "value")
_ANSWERS_HEADER = ("key", "question", "answer", "required")

_REQUIRED_VALUES = {"yes": True, "no": False}


class TemplateFormatError(ValueError):
    """The document does not follow the expected format."""


class _Section(NamedTuple):
    heading_line: int
    lines: list[tuple[int, str]]  # (line number, text)


class _Table(NamedTuple):
    header: list[str]
    header_line: int
    rows: list[tuple[int, list[str]]]  # (line number, cells)


def parse_template(text: str) -> Template:
    """Parse client-config.md into a validated Template."""
    sections = _split_sections(text)

    if _STANDARDS not in sections:
        raise TemplateFormatError("required section '## Standards' is missing.")
    if _ANSWERS not in sections:
        raise TemplateFormatError("required section '## Client answers' is missing.")

    standards = _parse_standards(sections[_STANDARDS])
    fields = _parse_client_answers(sections[_ANSWERS], taken_keys=set(standards))
    return Template(standards=standards, fields=fields)


def _split_sections(text: str) -> dict[str, _Section]:
    """Section title (casefolded) -> its heading line and body lines."""
    sections: dict[str, _Section] = {}
    current: _Section | None = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            title = line[3:].strip().casefold()
            if title in (_STANDARDS, _ANSWERS) and title in sections:
                raise TemplateFormatError(f"line {line_no}: duplicate section '{title}'.")
            current = sections.setdefault(title, _Section(line_no, []))
        elif current is not None:
            current.lines.append((line_no, line))

    return sections


def _read_table(name: str, section: _Section) -> _Table:
    """The one Markdown table of a known section."""
    table_lines: list[tuple[int, str]] = []
    table_ended = False

    for line_no, line in section.lines:
        stripped = line.strip()
        if not stripped:
            table_ended = table_ended or bool(table_lines)
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue  # HTML comments carry no data
        if not stripped.startswith("|"):
            raise TemplateFormatError(
                f"line {line_no} in '{name}': unexpected content outside the table."
            )
        if table_ended:
            raise TemplateFormatError(
                f"line {line_no} in '{name}': only one table is allowed per section."
            )
        table_lines.append((line_no, stripped))

    if len(table_lines) < 2:
        raise TemplateFormatError(
            f"line {section.heading_line} in '{name}': incomplete table "
            "(header and separator rows are required)."
        )

    header_line, header_text = table_lines[0]
    header = _split_cells(header_text)
    if any(not cell for cell in header):
        raise TemplateFormatError(f"line {header_line} in '{name}': empty header cell.")

    separator_line, separator_text = table_lines[1]
    separator = _split_cells(separator_text)
    if len(separator) != len(header) or not all(map(_is_separator_cell, separator)):
        raise TemplateFormatError(f"line {separator_line} in '{name}': invalid separator row.")

    rows = []
    for line_no, row_text in table_lines[2:]:
        cells = _split_cells(row_text)
        if len(cells) != len(header):
            raise TemplateFormatError(
                f"line {line_no} in '{name}': expected {len(header)} cells, found {len(cells)}."
            )
        rows.append((line_no, cells))

    return _Table(header, header_line, rows)


def _check_header(name: str, table: _Table, expected: tuple[str, ...]) -> None:
    found = tuple(cell.casefold() for cell in table.header)
    if found != expected:
        raise TemplateFormatError(
            f"line {table.header_line} in '{name}': expected columns "
            f"{' | '.join(expected)}, found {' | '.join(table.header)}."
        )


def _parse_standards(section: _Section) -> dict[str, str]:
    table = _read_table(_STANDARDS, section)
    _check_header(_STANDARDS, table, _STANDARDS_HEADER)

    standards: dict[str, str] = {}
    for line_no, (key, value) in table.rows:
        if not key:
            raise TemplateFormatError(f"line {line_no} in '{_STANDARDS}': empty key.")
        if key in standards:
            raise TemplateFormatError(f"line {line_no} in '{_STANDARDS}': duplicate key '{key}'.")
        if not value:
            raise TemplateFormatError(
                f"line {line_no} in '{_STANDARDS}': empty value for standard '{key}'."
            )
        standards[key] = value
    return standards


def _parse_client_answers(section: _Section, taken_keys: set[str]) -> tuple[Field, ...]:
    table = _read_table(_ANSWERS, section)
    _check_header(_ANSWERS, table, _ANSWERS_HEADER)

    taken = set(taken_keys)  # a client answer may not reuse a standard's key
    fields = []
    for line_no, (key, question, answer, required) in table.rows:
        if not key:
            raise TemplateFormatError(f"line {line_no} in '{_ANSWERS}': empty key.")
        if key in taken:
            raise TemplateFormatError(f"line {line_no} in '{_ANSWERS}': duplicate key '{key}'.")
        taken.add(key)
        fields.append(
            Field(
                key=key,
                question=question,
                answer=answer,
                required=_parse_required(required, line_no),
            )
        )
    return tuple(fields)


def _parse_required(value: str, line_no: int) -> bool:
    try:
        return _REQUIRED_VALUES[value.strip().casefold()]
    except KeyError:
        raise TemplateFormatError(
            f"line {line_no}: 'Required' must be 'yes' or 'no', found {value!r}."
        ) from None


def _split_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_cell(cell: str) -> bool:
    return "-" in cell and set(cell) <= {"-", ":", " "}