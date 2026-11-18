from collections.abc import Sequence
from typing import NamedTuple
 
from claw_skills_kit.models import Field, Template

 
_STANDARDS = "standards"
_ANSWERS = "client answers"
 
_STANDARDS_HEADER = ("setting", "standard")
_ANSWERS_HEADER = ("setting", "comes from", "suggested answer", "value")
_VALUE_COLUMN = 3  

_ANSWER_IS_REQUIRED = True

# 'Comes from' value of a question that exists only on one client's instance (not in the golden template).
INSTANCE_SOURCE = "Instance"
 
 
class TemplateFormatError(ValueError):
    """The document does not follow the expected format."""
 
 
class FillError(ValueError):
    """The answers cannot be written into the text, or the template does not match it."""
 
 
class _Section(NamedTuple):
    heading_line: int
    lines: list[tuple[int, str]]  # (line number, text)
 
 
class _Table(NamedTuple):
    header: list[str]
    header_line: int
    rows: list[tuple[int, list[str]]]  # (line number, cells)
    end_line: int  # line number of the table's last line (separator or last row)
 
 
def parse_template(text: str) -> Template:
    
    sections = _split_sections(text)
 
    if _STANDARDS not in sections:
        raise TemplateFormatError("required section '## Standards' is missing.")
    if _ANSWERS not in sections:
        raise TemplateFormatError("required section '## Client answers' is missing.")
 
    standards = _parse_standards(sections[_STANDARDS])
    fields = _parse_client_answers(sections[_ANSWERS], taken_keys=set(standards))
    return Template(standards=standards, fields=fields)
 
 
def _split_sections(text: str) -> dict[str, _Section]:

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

    table_lines: list[tuple[int, str]] = []
    table_ended = False
 
    for line_no, line in section.lines:
        stripped = line.strip()
        if not stripped:
            table_ended = table_ended or bool(table_lines)
            continue
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue  
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
 
    return _Table(header, header_line, rows, table_lines[-1][0])
 
 
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
    for line_no, (setting, standard) in table.rows:
        if not setting:
            raise TemplateFormatError(f"line {line_no} in '{_STANDARDS}': empty setting name.")
        if setting in standards:
            raise TemplateFormatError(
                f"line {line_no} in '{_STANDARDS}': duplicate setting '{setting}'."
            )
        if not standard:
            raise TemplateFormatError(
                f"line {line_no} in '{_STANDARDS}': empty standard for '{setting}'."
            )
        standards[setting] = standard
    return standards
 
 
def _parse_client_answers(section: _Section, taken_keys: set[str]) -> tuple[Field, ...]:
    table = _read_table(_ANSWERS, section)
    _check_header(_ANSWERS, table, _ANSWERS_HEADER)
 
    taken = set(taken_keys)  
    fields = []
    for line_no, (setting, comes_from, suggested, value) in table.rows:
        if not setting:
            raise TemplateFormatError(f"line {line_no} in '{_ANSWERS}': empty setting name.")
        if setting in taken:
            raise TemplateFormatError(
                f"line {line_no} in '{_ANSWERS}': duplicate setting '{setting}'."
            )
        taken.add(setting)
        fields.append(
            Field(
                key=setting,
                comes_from=comes_from,
                suggested=suggested,
                answer=value,
                required=_ANSWER_IS_REQUIRED,
            )
        )
    return tuple(fields)
 
 
def _split_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]
 
 
def _is_separator_cell(cell: str) -> bool:
    return "-" in cell and set(cell) <= {"-", ":", " "}
 

def _fits_in_a_cell(answer: str) -> bool:

    return "|" not in answer and (not answer or answer.splitlines() == [answer])
 
 
def _index_fields(template: Template) -> dict[str, Field]:

    by_key: dict[str, Field] = {}
    for field in template.fields:
        if field.key in by_key:
            raise FillError(f"Duplicate field key in template: {field.key!r}.")
        if not _fits_in_a_cell(field.answer):
            raise FillError(f"Answer for key {field.key!r} cannot contain '|' or line breaks.")
        by_key[field.key] = field
    return by_key
 
 
def _read_answers_table(text: str) -> _Table:

    sections = _split_sections(text)
    if _ANSWERS not in sections:
        raise TemplateFormatError("required section '## Client answers' is missing.")
    table = _read_table(_ANSWERS, sections[_ANSWERS])
    _check_header(_ANSWERS, table, _ANSWERS_HEADER)
    return table
 
 
def _check_keys_match(fields: dict[str, Field], table: _Table) -> None:

    row_keys: set[str] = set()
    for line_no, cells in table.rows:
        key = cells[0]
        if key in row_keys:
            raise TemplateFormatError(f"line {line_no} in '{_ANSWERS}': duplicate setting '{key}'.")
        row_keys.add(key)
 
    absent_from_text = sorted(set(fields) - row_keys)
    if absent_from_text:
        raise FillError("Template keys missing from the text: " + ", ".join(absent_from_text) + ".")
    absent_from_template = sorted(row_keys - set(fields))
    if absent_from_template:
        raise FillError(
            "Text keys missing from the template: " + ", ".join(absent_from_template) + "."
        )
 
 
def _patch_rows(text: str, table: _Table, fields: dict[str, Field]) -> str:

    lines = text.splitlines(keepends=True)
    for line_no, cells in table.rows:
        answer = fields[cells[0]].answer
        if answer == cells[_VALUE_COLUMN]:
            continue  
 
        raw = lines[line_no - 1]
        body = raw.rstrip("\r\n")
        ending = raw[len(body):]
        parts = body.split("|")
        parts[_VALUE_COLUMN + 1] = f" {answer} " if answer else " "
        lines[line_no - 1] = "|".join(parts) + ending
    return "".join(lines)
 
 
def fill_answers(text: str, template: Template) -> str:

    fields = _index_fields(template)
    table = _read_answers_table(text)
    _check_keys_match(fields, table)
    return _patch_rows(text, table, fields)

def is_instance_field(field: Field) -> bool:
    """True for a question added to one client's instance (marked in the 'Comes from' column)."""
    return field.comes_from.strip().casefold() == INSTANCE_SOURCE.casefold()


def append_fields(text: str, fields: Sequence[Field]) -> str:
    """Add one row per field at the end of the 'Client answers' table; every other byte stays the same.

    Rows are written as `| key | comes from | suggested | value |`. The result is parsed again, so a key
    that clashes with an existing setting or a standard is refused instead of written.
    """
    if not fields:
        return text
    table = _read_answers_table(text)
    existing = {cells[0] for _, cells in table.rows}
    new_keys: set[str] = set()
    rows = []
    for field in fields:
        cells = (field.key, field.comes_from, field.suggested, field.answer)
        if not field.key.strip():
            raise FillError("A new setting needs a name.")
        if not all(_fits_in_a_cell(cell) for cell in cells):
            raise FillError(f"Setting {field.key!r}: cells cannot contain '|' or line breaks.")
        if field.key in existing or field.key in new_keys:
            raise FillError(f"Setting {field.key!r} already exists.")
        new_keys.add(field.key)
        rows.append("|" + "|".join(f" {c.strip()} " if c.strip() else " " for c in cells) + "|")

    lines = text.splitlines(keepends=True)
    last = lines[table.end_line - 1]
    body = last.rstrip("\r\n")
    ending = last[len(body):]
    if ending:  # the table's last line ends with a newline: each new row keeps the same ending
        new_lines = [row + ending for row in rows]
    else:  # the table ends the file with no final newline: keep it that way
        newline = next((ln[len(ln.rstrip("\r\n")):] for ln in lines if ln.endswith("\n")), "\n")
        lines[table.end_line - 1] = body + newline
        new_lines = [row + newline for row in rows]
        new_lines[-1] = rows[-1]
    lines[table.end_line:table.end_line] = new_lines
    result = "".join(lines)
    parse_template(result)  # raises TemplateFormatError if the new rows break the document
    return result


_SUGGESTED_COLUMN = 2


def _find_row(table: _Table, key: str) -> int:
    for line_no, cells in table.rows:
        if cells[0] == key:
            return line_no
    raise FillError(f"Setting {key!r} is not in the client answers.")


def _set_cell(line: str, column: int, value: str) -> str:
    body = line.rstrip("\r\n")
    ending = line[len(body):]
    parts = body.split("|")
    parts[column + 1] = f" {value} " if value else " "
    return "|".join(parts) + ending


def update_field(text: str, key: str, *, suggested: str | None = None, answer: str | None = None) -> str:
    """Change the suggested answer and/or the value of one row; every other byte stays the same."""
    for value in (suggested, answer):
        if value is not None and not _fits_in_a_cell(value.strip()):
            raise FillError(f"Setting {key!r}: cells cannot contain '|' or line breaks.")
    table = _read_answers_table(text)
    line_no = _find_row(table, key)
    lines = text.splitlines(keepends=True)
    if suggested is not None:
        lines[line_no - 1] = _set_cell(lines[line_no - 1], _SUGGESTED_COLUMN, suggested.strip())
    if answer is not None:
        lines[line_no - 1] = _set_cell(lines[line_no - 1], _VALUE_COLUMN, answer.strip())
    return "".join(lines)


def remove_field(text: str, key: str) -> str:
    """Delete one row of the client answers table; every other byte stays the same."""
    table = _read_answers_table(text)
    line_no = _find_row(table, key)
    lines = text.splitlines(keepends=True)
    removed = lines.pop(line_no - 1)
    if line_no - 1 == len(lines) and not removed.endswith("\n") and lines:
        # the removed row was the last line with no final newline: keep the file without one
        prev = lines[-1]
        lines[-1] = prev.rstrip("\r\n")
    return "".join(lines)
