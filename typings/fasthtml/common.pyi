"""FastHTML 0.13 API surface consumed by APasz Hub."""

A: object
Article: object
Div: object
Footer: object
H1: object
H2: object
Header: object
Img: object
Li: object
Link: object
Main: object
Meta: object
Nav: object
P: object
Picture: object
Section: object
Script: object
Span: object
Source: object
Ul: object

def FastHTML(**options: object) -> object: ...
def serve(**options: object) -> None: ...
def to_xml(
    *nodes: object,
    lvl: int = 0,
    indent: bool = True,
    do_escape: bool = True,
) -> object: ...
