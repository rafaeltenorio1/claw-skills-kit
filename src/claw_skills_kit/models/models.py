from dataclasses import dataclass

@dataclass(frozen=True)
class Field:
    key: str
    question: str
    answer: str          # "" quando em branco
    required: bool

@dataclass(frozen=True)
class Template:
    standards: dict[str, str]
    fields: tuple[Field, ...]