"""Security and safety tests for inline SVG rendering and validation.

Covers AC-010.
"""
from __future__ import annotations

import pytest

from lib.visual_style.layouts import build_preset_graph
from lib.visual_style.spec import DiagramNode, NodeKind
from lib.visual_style.svg_renderer import render_inline_svg_dom
from lib.visual_style.validation import (
    DiagramSecurityError,
    validate_diagram_plan_data,
    validate_security_string,
)


@pytest.mark.parametrize("malicious_string", [
    "<script>alert(1)</script>",
    "<SCRIPT SRC='http://evil.com/xss.js'></SCRIPT>",
    "<foreignObject width='100' height='100'><body xmlns='http://www.w3.org/1999/xhtml'><script>steal()</script></body></foreignObject>",
    "<iframe src='javascript:alert(1)'></iframe>",
    "<img src=x onerror='alert(1)'>",
    "javascript:void(0)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
])
def test_reject_malicious_xss_payloads(malicious_string: str):
    """Validation must reject dangerous script/iframe/foreignObject/javascript injection."""
    with pytest.raises(DiagramSecurityError, match="disallowed active content"):
        validate_security_string(malicious_string)


def test_svg_renderer_escapes_xml_special_characters():
    """XML special characters (<, >, &, \", ') must be strictly escaped in rendered text."""
    graph = build_preset_graph("context_memory")
    # Replace first node label with string containing special chars
    special_label = 'Memory & Context <rules> "persistent" \'v1\''
    graph.nodes[0] = DiagramNode(
        id=graph.nodes[0].id,
        label=special_label,
        kind=graph.nodes[0].kind,
        x=graph.nodes[0].x,
        y=graph.nodes[0].y,
        width=graph.nodes[0].width,
        height=graph.nodes[0].height,
    )

    rendered_svg = render_inline_svg_dom(graph)
    # Check that unescaped characters do NOT appear in the SVG text
    assert "<rules>" not in rendered_svg
    assert "Memory &amp; Context &lt;rules&gt; &quot;persistent&quot; &#x27;v1&#x27;" in rendered_svg
    assert "<script" not in rendered_svg
    assert "<foreignObject" not in rendered_svg
    assert "technical-diagram-svg" in rendered_svg
