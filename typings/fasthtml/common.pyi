"""FastHTML 0.13 API surface consumed by APasz Hub."""

A: object
Article: object
Button: object
Details: object
Dialog: object
Div: object
Footer: object
Form: object
H1: object
H2: object
Header: object
Img: object
Input: object
Label: object
Li: object
Link: object
Main: object
Meta: object
Nav: object
Option: object
P: object
Picture: object
Select: object
Section: object
Script: object
Span: object
Source: object
Summary: object
Textarea: object
Ul: object

def FastHTML(**options: object) -> object: ...
def HttpHeader(name: str, value: str) -> object: ...
def serve(**options: object) -> None: ...
def to_xml(
    *nodes: object,
    lvl: int = 0,
    indent: bool = True,
    do_escape: bool = True,
) -> object: ...
