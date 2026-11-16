from dataclasses import dataclass
 
 
@dataclass(frozen=True)
class Field:
 
    key: str  
    comes_from: str  
    suggested: str  
    answer: str  
    required: bool = True 
 
 
@dataclass(frozen=True)
class Template:
 
    standards: dict[str, str]  
    fields: tuple[Field, ...] 