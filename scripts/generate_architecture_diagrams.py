#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Generate the two architecture diagrams from one shared layout."""

from __future__ import annotations

import argparse
import base64
# This generator only constructs XML from trusted constants; it never parses XML input.
import xml.etree.ElementTree as ET  # nosemgrep  # nosec B405
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "images"
ICON_DIR = IMAGE_DIR / "aws-icons"
SCALE = 2
CANVAS_WIDTH = 1400
CANVAS_HEIGHT = 720

AWS_DARK = "#232F3E"
AWS_ORANGE = "#FF9900"
AWS_BLUE = "#0972D3"
AWS_MAGENTA = "#E7157B"
AWS_TEAL = "#007D84"
AWS_GRAY = "#D5DBDB"
LIGHT_BLUE = "#EAF3FA"
LIGHT_GRAY = "#F7F7F7"
TEXT_GRAY = "#414D5C"
WHITE = "#FFFFFF"

ICON_FILES = {
    "account": "AWS-Account_32.png",
    "agentcore": "Arch_Amazon-Bedrock-AgentCore_64.png",
    "bedrock": "Arch_Amazon-Bedrock_64.png",
    "iam": "Arch_AWS-Identity-and-Access-Management_64.png",
    "lambda": "Arch_AWS-Lambda_64.png",
    "redshift": "Arch_Amazon-Redshift_64.png",
    "sts": "Res_AWS-Identity-Access-Management_AWS-STS_48.png",
}

FONT_REGULAR_CANDIDATES = (
    "/Library/Fonts/Amazon Ember.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
FONT_BOLD_CANDIDATES = (
    "/Library/Fonts/Amazon Ember Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


@dataclass(frozen=True)
class Node:
    key: str
    label: str
    x: int
    y: int = 245
    width: int = 122
    height: int = 142
    icon: str | None = None
    badge: str | None = None
    accent: str = AWS_DARK
    label_size: int = 13

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    label: str
    color: str = AWS_DARK
    dashed: bool = False


@dataclass(frozen=True)
class RuntimeBoundary:
    x: int
    y: int
    width: int
    height: int
    label: str = "AgentCore Runtime"


@dataclass(frozen=True)
class Diagram:
    name: str
    title: str
    subtitle: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    model_links: tuple[Edge, ...]
    runtime_boundary: RuntimeBoundary


def resolve_font(candidates: Iterable[str]) -> str:
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("No supported font was found")


FONT_REGULAR = resolve_font(FONT_REGULAR_CANDIDATES)
FONT_BOLD = resolve_font(FONT_BOLD_CANDIDATES)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size * SCALE)


def diagram_definitions() -> tuple[Diagram, Diagram]:
    common_tail = (
        Node("sts", "AWS STS", 790, icon="sts"),
        Node("role", "KB access\nIAM role", 945, icon="iam"),
        Node("kb", "Amazon Bedrock\nKnowledge Base", 1100, icon="bedrock"),
        Node("redshift", "Amazon Redshift\nServerless", 1255, icon="redshift"),
        Node(
            "kb_model",
            "Claude Haiku 4.5\nGeneration model",
            1100,
            470,
            icon="bedrock",
            accent=AWS_TEAL,
        ),
    )

    code = Diagram(
        name="architecture",
        title="Variant 1: Code-based Strands agent",
        subtitle="Customer-managed Strands loop and local MCP server packaged together in AgentCore Runtime",
        nodes=(
            Node("user", "User", 20, badge="U", accent=AWS_BLUE),
            Node("ui", "Streamlit\nchat UI", 165, badge="UI", accent=AWS_BLUE),
            Node("strands", "Strands Agent\nCustomer agent loop", 360, 255, badge="S", accent=AWS_TEAL),
            Node("mcp", "Local MCP server\nsubprocess", 560, 255, badge="MCP", accent=AWS_TEAL),
            *common_tail,
            Node(
                "agent_model",
                "Amazon Nova Pro\nAgent model",
                360,
                470,
                icon="bedrock",
                accent=AWS_TEAL,
            ),
        ),
        edges=(
            Edge("user", "ui", "1  Question"),
            Edge("ui", "strands", "2  Invoke"),
            Edge("strands", "mcp", "3  Tool call"),
            Edge("mcp", "sts", "4  AssumeRole", AWS_MAGENTA),
            Edge("sts", "role", "", AWS_MAGENTA),
            Edge("role", "kb", "5  RetrieveAndGenerate"),
            Edge("kb", "redshift", "6  Structured query"),
        ),
        model_links=(
            Edge("agent_model", "strands", "model", AWS_TEAL, True),
            Edge("kb_model", "kb", "model", AWS_TEAL, True),
        ),
        runtime_boundary=RuntimeBoundary(325, 190, 410, 440),
    )

    harness = Diagram(
        name="architecture_harness",
        title="Variant 2: Declarative AgentCore harness",
        subtitle="Managed Strands-powered loop in AgentCore Runtime with Gateway and an AWS Lambda tool",
        nodes=(
            Node("user", "User", 20, badge="U", accent=AWS_BLUE),
            Node("ui", "Streamlit\nchat UI", 165, badge="UI", accent=AWS_BLUE),
            Node(
                "harness",
                "AgentCore harness\nStrands loop\nMCP client",
                325,
                255,
                badge="S",
                accent=AWS_TEAL,
                label_size=11,
            ),
            Node(
                "gateway",
                "AgentCore Gateway\nMCP tool endpoint",
                480,
                icon="agentcore",
                label_size=12,
            ),
            Node("lambda", "AWS Lambda\nKB query tool", 635, icon="lambda"),
            *common_tail,
            Node(
                "agent_model",
                "Amazon Nova Pro\nAgent model",
                325,
                470,
                icon="bedrock",
                accent=AWS_TEAL,
            ),
        ),
        edges=(
            Edge("user", "ui", "1  Question"),
            Edge("ui", "harness", "2  InvokeHarness"),
            Edge("harness", "gateway", "3  MCP tool call"),
            Edge("gateway", "lambda", "4  Invoke tool"),
            Edge("lambda", "sts", "5  AssumeRole", AWS_MAGENTA),
            Edge("sts", "role", "", AWS_MAGENTA),
            Edge("role", "kb", "6  RetrieveAndGenerate"),
            Edge("kb", "redshift", "7  Structured query"),
        ),
        model_links=(
            Edge("agent_model", "harness", "model", AWS_TEAL, True),
            Edge("kb_model", "kb", "model", AWS_TEAL, True),
        ),
        runtime_boundary=RuntimeBoundary(310, 190, 152, 440),
    )
    return code, harness


def rounded_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int,
    fill: str,
    outline: str,
    width: int,
) -> None:
    draw.rounded_rectangle(
        tuple(value * SCALE for value in box),
        radius=radius * SCALE,
        fill=fill,
        outline=outline,
        width=width * SCALE,
    )


def draw_text_centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    *,
    spacing: int = 3,
) -> None:
    left, top, right, bottom = (value * SCALE for value in box)
    lines = text.splitlines()
    heights: list[int] = []
    widths: list[int] = []
    for line in lines:
        bounds = draw.textbbox((0, 0), line, font=text_font)
        widths.append(bounds[2] - bounds[0])
        heights.append(bounds[3] - bounds[1])
    total_height = sum(heights) + spacing * SCALE * (len(lines) - 1)
    y = top + (bottom - top - total_height) / 2
    for line, line_width, line_height in zip(lines, widths, heights):
        draw.text(
            (left + (right - left - line_width) / 2, y),
            line,
            font=text_font,
            fill=fill,
        )
        y += line_height + spacing * SCALE


def load_icon(name: str, size: int) -> Image.Image:
    path = ICON_DIR / ICON_FILES[name]
    image = Image.open(path).convert("RGBA")
    image.thumbnail((size * SCALE, size * SCALE), Image.Resampling.LANCZOS)
    return image


def paste_icon(canvas: Image.Image, name: str, box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    size = min(right - left, bottom - top)
    icon = load_icon(name, size)
    x = (left + (right - left) / 2) * SCALE - icon.width / 2
    y = (top + (bottom - top) / 2) * SCALE - icon.height / 2
    canvas.alpha_composite(icon, (round(x), round(y)))


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str,
    *,
    dashed: bool = False,
) -> None:
    x1, y1 = (value * SCALE for value in start)
    x2, y2 = (value * SCALE for value in end)
    width = 2 * SCALE
    if dashed:
        dash = 7 * SCALE
        gap = 5 * SCALE
        distance = abs(y2 - y1) if x1 == x2 else abs(x2 - x1)
        cursor = 0
        while cursor < distance:
            segment_end = min(cursor + dash, distance)
            if x1 == x2:
                direction = 1 if y2 >= y1 else -1
                draw.line(
                    (x1, y1 + cursor * direction, x2, y1 + segment_end * direction),
                    fill=color,
                    width=width,
                )
            else:
                direction = 1 if x2 >= x1 else -1
                draw.line(
                    (x1 + cursor * direction, y1, x1 + segment_end * direction, y2),
                    fill=color,
                    width=width,
                )
            cursor += dash + gap
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)

    arrow = 7 * SCALE
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 >= x1 else -1
        points = (
            (x2, y2),
            (x2 - direction * arrow, y2 - arrow // 2),
            (x2 - direction * arrow, y2 + arrow // 2),
        )
    else:
        direction = 1 if y2 >= y1 else -1
        points = (
            (x2, y2),
            (x2 - arrow // 2, y2 - direction * arrow),
            (x2 + arrow // 2, y2 - direction * arrow),
        )
    draw.polygon(points, fill=color)


def draw_account_boundary(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
) -> None:
    left, top, right, bottom = box
    draw.rectangle(
        tuple(value * SCALE for value in box),
        fill=WHITE,
        outline=AWS_MAGENTA,
        width=2 * SCALE,
    )
    draw.rectangle(
        (left * SCALE, top * SCALE, right * SCALE, (top + 40) * SCALE),
        fill="#FFF4FA",
    )
    paste_icon(canvas, "account", (left + 12, top + 9, left + 34, top + 31))
    draw.text(
        ((left + 43) * SCALE, (top + 10) * SCALE),
        title,
        font=font(15, True),
        fill=AWS_MAGENTA,
    )


def draw_runtime_boundary(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    boundary: RuntimeBoundary,
) -> None:
    left = boundary.x
    top = boundary.y
    right = left + boundary.width
    bottom = top + boundary.height
    rounded_rectangle(
        draw,
        (left, top, right, bottom),
        radius=7,
        fill="#F4F8FB",
        outline=AWS_BLUE,
        width=2,
    )
    draw.rounded_rectangle(
        (
            left * SCALE,
            top * SCALE,
            right * SCALE,
            (top + 40) * SCALE,
        ),
        radius=7 * SCALE,
        fill=LIGHT_BLUE,
        outline=None,
    )
    draw.rectangle(
        (
            left * SCALE,
            (top + 32) * SCALE,
            right * SCALE,
            (top + 40) * SCALE,
        ),
        fill=LIGHT_BLUE,
    )
    draw.line(
        (
            left * SCALE,
            (top + 40) * SCALE,
            right * SCALE,
            (top + 40) * SCALE,
        ),
        fill=AWS_BLUE,
        width=1 * SCALE,
    )
    paste_icon(canvas, "agentcore", (left + 9, top + 8, left + 33, top + 32))
    draw.text(
        ((left + 39) * SCALE, (top + 11) * SCALE),
        boundary.label,
        font=font(12, True),
        fill=AWS_DARK,
    )


def draw_node(canvas: Image.Image, draw: ImageDraw.ImageDraw, node: Node) -> None:
    rounded_rectangle(
        draw,
        (node.x, node.y, node.x + node.width, node.y + node.height),
        radius=7,
        fill=WHITE,
        outline=AWS_GRAY,
        width=1,
    )
    draw.rectangle(
        (
            node.x * SCALE,
            node.y * SCALE,
            (node.x + 5) * SCALE,
            (node.y + node.height) * SCALE,
        ),
        fill=node.accent,
    )
    if node.icon:
        paste_icon(
            canvas,
            node.icon,
            (node.x + 36, node.y + 15, node.x + node.width - 30, node.y + 74),
        )
    else:
        center_x = (node.x + node.width // 2) * SCALE
        center_y = (node.y + 45) * SCALE
        radius = 27 * SCALE
        draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            fill=node.accent,
        )
        draw_text_centered(
            draw,
            (node.x + 25, node.y + 20, node.x + node.width - 25, node.y + 70),
            node.badge or "",
            font(13 if len(node.badge or "") > 1 else 22, True),
            WHITE,
        )
    draw_text_centered(
        draw,
        (node.x + 7, node.y + 80, node.x + node.width - 7, node.y + node.height - 8),
        node.label,
        font(node.label_size, True),
        AWS_DARK,
        spacing=2,
    )


def draw_edge_label(
    draw: ImageDraw.ImageDraw,
    start_x: int,
    end_x: int,
    y: int,
    label: str,
    color: str,
) -> None:
    if not label:
        return
    text_font = font(10, True)
    bounds = draw.textbbox((0, 0), label, font=text_font)
    text_width = (bounds[2] - bounds[0]) // SCALE
    center = (start_x + end_x) // 2
    padding = 4
    rounded_rectangle(
        draw,
        (
            center - text_width // 2 - padding,
            y - 10,
            center + text_width // 2 + padding,
            y + 10,
        ),
        radius=4,
        fill=WHITE,
        outline=AWS_GRAY,
        width=1,
    )
    draw_text_centered(
        draw,
        (center - text_width // 2 - padding, y - 10, center + text_width // 2 + padding, y + 10),
        label,
        text_font,
        color,
    )


def render_png(diagram: Diagram, output: Path) -> None:
    canvas = Image.new(
        "RGBA",
        (CANVAS_WIDTH * SCALE, CANVAS_HEIGHT * SCALE),
        WHITE,
    )
    draw = ImageDraw.Draw(canvas)

    draw.text((24 * SCALE, 22 * SCALE), diagram.title, font=font(29, True), fill=AWS_DARK)
    draw.text((24 * SCALE, 65 * SCALE), diagram.subtitle, font=font(16), fill=TEXT_GRAY)
    draw.line(
        (24 * SCALE, 103 * SCALE, 1376 * SCALE, 103 * SCALE),
        fill=AWS_ORANGE,
        width=4 * SCALE,
    )

    draw_account_boundary(canvas, draw, (310, 135, 925, 640), "Agent account")
    draw_account_boundary(canvas, draw, (935, 135, 1385, 640), "Knowledge Base account")
    draw_runtime_boundary(canvas, draw, diagram.runtime_boundary)

    nodes = {node.key: node for node in diagram.nodes}
    for edge in diagram.edges:
        source = nodes[edge.source]
        target = nodes[edge.target]
        draw_arrow(
            draw,
            (source.x + source.width, source.center_y),
            (target.x, target.center_y),
            edge.color,
        )
        draw_edge_label(
            draw,
            source.x + source.width,
            target.x,
            source.y - 16,
            edge.label,
            edge.color,
        )

    for edge in diagram.model_links:
        source = nodes[edge.source]
        target = nodes[edge.target]
        draw_arrow(
            draw,
            (source.center_x, source.y),
            (target.center_x, target.y + target.height),
            edge.color,
            dashed=True,
        )

    for node in diagram.nodes:
        draw_node(canvas, draw, node)

    draw.text(
        (24 * SCALE, 674 * SCALE),
        "Response and citations return through the selected orchestration path.",
        font=font(12),
        fill=TEXT_GRAY,
    )
    source_text = "AWS Architecture Icons package: 2026-04-30"
    bounds = draw.textbbox((0, 0), source_text, font=font(10))
    draw.text(
        ((1376 * SCALE) - (bounds[2] - bounds[0]), 677 * SCALE),
        source_text,
        font=font(10),
        fill=TEXT_GRAY,
    )

    canvas.convert("RGB").save(output, format="PNG", optimize=True)


def draw_polyline_arrow(
    draw: ImageDraw.ImageDraw,
    points: tuple[tuple[int, int], ...],
    color: str,
) -> None:
    scaled = tuple((x * SCALE, y * SCALE) for x, y in points)
    draw.line(scaled[:-1], fill=color, width=2 * SCALE, joint="curve")
    draw_arrow(draw, points[-2], points[-1], color)


def render_overview_png(output: Path) -> None:
    canvas = Image.new(
        "RGBA",
        (CANVAS_WIDTH * SCALE, CANVAS_HEIGHT * SCALE),
        WHITE,
    )
    draw = ImageDraw.Draw(canvas)

    draw.text(
        (CANVAS_WIDTH * SCALE // 2, 21 * SCALE),
        "Two AgentCore implementations",
        font=font(29, True),
        fill=AWS_DARK,
        anchor="ma",
    )
    draw.text(
        (CANVAS_WIDTH * SCALE // 2, 61 * SCALE),
        "One cross-account security pattern",
        font=font(22, True),
        fill=AWS_DARK,
        anchor="ma",
    )
    draw.line(
        (24 * SCALE, 103 * SCALE, 1376 * SCALE, 103 * SCALE),
        fill=AWS_ORANGE,
        width=4 * SCALE,
    )

    panel_top = 130
    panel_bottom = 465
    rounded_rectangle(
        draw,
        (35, panel_top, 685, panel_bottom),
        radius=7,
        fill="#F7FAFC",
        outline=AWS_GRAY,
        width=1,
    )
    rounded_rectangle(
        draw,
        (715, panel_top, 1365, panel_bottom),
        radius=7,
        fill=LIGHT_GRAY,
        outline=AWS_GRAY,
        width=1,
    )
    draw.rectangle((35 * SCALE, panel_top * SCALE, 685 * SCALE, 178 * SCALE), fill=AWS_BLUE)
    draw.rectangle((715 * SCALE, panel_top * SCALE, 1365 * SCALE, 178 * SCALE), fill=AWS_ORANGE)
    draw_text_centered(
        draw,
        (45, panel_top, 675, 178),
        "Variant 1: Code-based Strands agent",
        font(18, True),
        WHITE,
    )
    draw_text_centered(
        draw,
        (725, panel_top, 1355, 178),
        "Variant 2: Declarative AgentCore harness",
        font(18, True),
        WHITE,
    )

    left_runtime = RuntimeBoundary(60, 195, 400, 245)
    right_runtime = RuntimeBoundary(735, 195, 150, 245)
    draw_runtime_boundary(canvas, draw, left_runtime)
    draw_runtime_boundary(canvas, draw, right_runtime)

    overview_nodes = (
        Node("overview_strands", "Strands Agent\nCustomer agent loop", 85, 255, badge="S", accent=AWS_TEAL),
        Node("overview_mcp", "Local MCP server\nsubprocess", 285, 255, badge="MCP", accent=AWS_TEAL),
        Node(
            "overview_harness",
            "AgentCore harness\nStrands loop\nMCP client",
            749,
            255,
            badge="S",
            accent=AWS_TEAL,
            label_size=11,
        ),
        Node(
            "overview_gateway",
            "AgentCore Gateway\nMCP tool endpoint",
            930,
            255,
            icon="agentcore",
            label_size=12,
        ),
        Node("overview_lambda", "AWS Lambda\nKB query tool", 1110, 255, icon="lambda"),
        Node("overview_sts", "AWS STS", 400, 520, icon="sts"),
        Node("overview_role", "KB access\nIAM role", 555, 520, icon="iam"),
        Node("overview_kb", "Amazon Bedrock\nKnowledge Base", 710, 520, icon="bedrock"),
        Node("overview_redshift", "Amazon Redshift\nServerless", 865, 520, icon="redshift"),
    )
    overview = {node.key: node for node in overview_nodes}

    draw_arrow(
        draw,
        (
            overview["overview_strands"].x + overview["overview_strands"].width,
            overview["overview_strands"].center_y,
        ),
        (overview["overview_mcp"].x, overview["overview_mcp"].center_y),
        AWS_DARK,
    )
    draw_arrow(
        draw,
        (
            overview["overview_harness"].x + overview["overview_harness"].width,
            overview["overview_harness"].center_y,
        ),
        (overview["overview_gateway"].x, overview["overview_gateway"].center_y),
        AWS_DARK,
    )
    draw_arrow(
        draw,
        (
            overview["overview_gateway"].x + overview["overview_gateway"].width,
            overview["overview_gateway"].center_y,
        ),
        (overview["overview_lambda"].x, overview["overview_lambda"].center_y),
        AWS_DARK,
    )

    sts = overview["overview_sts"]
    draw_polyline_arrow(
        draw,
        (
            (overview["overview_mcp"].center_x, overview["overview_mcp"].y + overview["overview_mcp"].height),
            (overview["overview_mcp"].center_x, 485),
            (sts.center_x, 485),
            (sts.center_x, sts.y),
        ),
        AWS_MAGENTA,
    )
    draw_polyline_arrow(
        draw,
        (
            (overview["overview_lambda"].center_x, overview["overview_lambda"].y + overview["overview_lambda"].height),
            (overview["overview_lambda"].center_x, 485),
            (sts.center_x, 485),
            (sts.center_x, sts.y),
        ),
        AWS_MAGENTA,
    )
    for source_key, target_key in (
        ("overview_sts", "overview_role"),
        ("overview_role", "overview_kb"),
        ("overview_kb", "overview_redshift"),
    ):
        source = overview[source_key]
        target = overview[target_key]
        draw_arrow(
            draw,
            (source.x + source.width, source.center_y),
            (target.x, target.center_y),
            AWS_MAGENTA if source_key == "overview_sts" else AWS_DARK,
        )

    for node in overview_nodes:
        draw_node(canvas, draw, node)

    draw.text(
        (1045 * SCALE, 543 * SCALE),
        "Shared cross-account access path",
        font=font(14, True),
        fill=AWS_MAGENTA,
    )
    source_text = "AWS Architecture Icons package: 2026-04-30"
    bounds = draw.textbbox((0, 0), source_text, font=font(10))
    draw.text(
        ((1376 * SCALE) - (bounds[2] - bounds[0]), 690 * SCALE),
        source_text,
        font=font(10),
        fill=TEXT_GRAY,
    )

    canvas.convert("RGB").save(output, format="PNG", optimize=True)


def image_data_uri(icon_name: str) -> str:
    data = (ICON_DIR / ICON_FILES[icon_name]).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    # draw.io styles use semicolons as property separators. Its embedded-image
    # syntax therefore omits the standard data-URI ";base64" marker.
    return f"data:image/png,{encoded}"


def add_geometry(cell: ET.Element, x: int, y: int, width: int, height: int) -> None:
    ET.SubElement(
        cell,
        "mxGeometry",
        {
            "x": str(x),
            "y": str(y),
            "width": str(width),
            "height": str(height),
            "as": "geometry",
        },
    )


def add_vertex(
    root: ET.Element,
    cell_id: str,
    value: str,
    style: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> ET.Element:
    cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": cell_id,
            "value": value,
            "style": style,
            "vertex": "1",
            "parent": "1",
        },
    )
    add_geometry(cell, x, y, width, height)
    return cell


def add_drawio_edge(
    root: ET.Element,
    cell_id: str,
    edge: Edge,
    source: str,
    target: str,
) -> None:
    style = (
        f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor={edge.color};"
        "strokeWidth=2;endArrow=block;endFill=1;"
    )
    if edge.dashed:
        style += "dashed=1;dashPattern=6 4;"
    cell = ET.SubElement(
        root,
        "mxCell",
        {
            "id": cell_id,
            "value": edge.label,
            "style": style,
            "edge": "1",
            "parent": "1",
            "source": source,
            "target": target,
        },
    )
    ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})


def render_drawio(diagram: Diagram, output: Path) -> None:
    mxfile = ET.Element(
        "mxfile",
        {
            "host": "app.diagrams.net",
            "modified": "2026-07-21T00:00:00.000Z",
            "agent": "Codex architecture diagram generator",
            "version": "24.7.17",
            "type": "device",
        },
    )
    page = ET.SubElement(mxfile, "diagram", {"id": diagram.name, "name": "Page-1"})
    model = ET.SubElement(
        page,
        "mxGraphModel",
        {
            "dx": "1400",
            "dy": "720",
            "grid": "1",
            "gridSize": "10",
            "guides": "1",
            "tooltips": "1",
            "connect": "1",
            "arrows": "1",
            "fold": "1",
            "page": "1",
            "pageScale": "1",
            "pageWidth": "1400",
            "pageHeight": "720",
            "math": "0",
            "shadow": "0",
        },
    )
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    text_style = (
        f"text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;"
        f"fontColor={AWS_DARK};fontFamily=Amazon Ember;"
    )
    add_vertex(root, "title", diagram.title, text_style + "fontSize=29;fontStyle=1;", 24, 18, 1000, 42)
    add_vertex(root, "subtitle", diagram.subtitle, text_style + f"fontSize=16;fontColor={TEXT_GRAY};", 24, 60, 1150, 32)
    add_vertex(root, "rule", "", f"shape=line;strokeColor={AWS_ORANGE};strokeWidth=4;", 24, 100, 1352, 4)

    boundary_style = f"rounded=0;whiteSpace=wrap;html=1;fillColor={WHITE};strokeColor={AWS_MAGENTA};strokeWidth=2;"
    add_vertex(root, "agent-account", "", boundary_style, 310, 135, 615, 505)
    add_vertex(root, "kb-account", "", boundary_style, 935, 135, 450, 505)
    header_style = (
        f"rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
        f"spacingLeft=42;fontStyle=1;fontSize=15;fontColor={AWS_MAGENTA};"
        f"fillColor=#FFF4FA;strokeColor=none;fontFamily=Amazon Ember;"
    )
    add_vertex(root, "agent-account-header", "Agent account", header_style, 312, 137, 611, 38)
    add_vertex(root, "kb-account-header", "Knowledge Base account", header_style, 937, 137, 446, 38)
    account_image_style = (
        f"shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=0;"
        f"aspect=fixed;image={image_data_uri('account')};"
    )
    add_vertex(root, "agent-account-icon", "", account_image_style, 322, 144, 22, 22)
    add_vertex(root, "kb-account-icon", "", account_image_style, 947, 144, 22, 22)

    runtime = diagram.runtime_boundary
    runtime_style = (
        f"rounded=1;arcSize=7;whiteSpace=wrap;html=1;fillColor=#F4F8FB;"
        f"strokeColor={AWS_BLUE};strokeWidth=2;"
    )
    add_vertex(
        root,
        "runtime-boundary",
        "",
        runtime_style,
        runtime.x,
        runtime.y,
        runtime.width,
        runtime.height,
    )
    runtime_header_style = (
        f"rounded=1;arcSize=7;whiteSpace=wrap;html=1;align=left;verticalAlign=middle;"
        f"spacingLeft=39;fontStyle=1;fontSize=12;fontColor={AWS_DARK};"
        f"fillColor={LIGHT_BLUE};strokeColor=none;fontFamily=Amazon Ember;"
    )
    add_vertex(
        root,
        "runtime-header",
        runtime.label,
        runtime_header_style,
        runtime.x + 2,
        runtime.y + 2,
        runtime.width - 4,
        38,
    )
    runtime_icon_style = (
        "shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=0;"
        f"aspect=fixed;image={image_data_uri('agentcore')};"
    )
    add_vertex(
        root,
        "runtime-icon",
        "",
        runtime_icon_style,
        runtime.x + 10,
        runtime.y + 9,
        22,
        22,
    )

    for node in diagram.nodes:
        card_style = (
            f"rounded=1;arcSize=7;whiteSpace=wrap;html=1;fillColor={WHITE};"
            f"strokeColor={AWS_GRAY};strokeWidth=1;"
        )
        add_vertex(root, f"node-{node.key}", "", card_style, node.x, node.y, node.width, node.height)
        add_vertex(
            root,
            f"accent-{node.key}",
            "",
            f"rounded=0;fillColor={node.accent};strokeColor=none;",
            node.x,
            node.y,
            5,
            node.height,
        )
        if node.icon:
            image_style = (
                "shape=image;verticalLabelPosition=bottom;verticalAlign=top;imageAspect=0;"
                f"aspect=fixed;image={image_data_uri(node.icon)};"
            )
            add_vertex(
                root,
                f"icon-{node.key}",
                "",
                image_style,
                node.x + 39,
                node.y + 15,
                52,
                58,
            )
        else:
            add_vertex(
                root,
                f"badge-{node.key}",
                node.badge or "",
                (
                    f"ellipse;whiteSpace=wrap;html=1;fillColor={node.accent};strokeColor=none;"
                    f"fontColor={WHITE};fontStyle=1;fontSize={13 if len(node.badge or '') > 1 else 22};"
                    "fontFamily=Amazon Ember;"
                ),
                node.x + 34,
                node.y + 18,
                54,
                54,
            )
        label_style = (
            f"text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;"
            f"whiteSpace=wrap;rounded=0;fontColor={AWS_DARK};fontStyle=1;"
            f"fontSize={node.label_size};"
            "fontFamily=Amazon Ember;"
        )
        add_vertex(
            root,
            f"label-{node.key}",
            node.label.replace("\n", "<br>"),
            label_style,
            node.x + 7,
            node.y + 78,
            node.width - 14,
            node.height - 84,
        )

    for index, edge in enumerate((*diagram.edges, *diagram.model_links), 1):
        add_drawio_edge(
            root,
            f"edge-{index}",
            edge,
            f"node-{edge.source}",
            f"node-{edge.target}",
        )

    add_vertex(
        root,
        "response-note",
        "Response and citations return through the selected orchestration path.",
        text_style + f"fontSize=12;fontColor={TEXT_GRAY};",
        24,
        670,
        780,
        24,
    )
    add_vertex(
        root,
        "icon-source",
        "AWS Architecture Icons package: 2026-04-30",
        text_style + f"fontSize=10;fontColor={TEXT_GRAY};align=right;",
        1010,
        670,
        366,
        24,
    )

    ET.indent(mxfile, space="  ")
    validate_drawio_images(mxfile, output)
    tree = ET.ElementTree(mxfile)
    tree.write(output, encoding="utf-8", xml_declaration=True)


def validate_drawio_images(root: ET.Element, path: Path) -> None:
    marker = "image=data:image/png,"
    image_count = 0
    for cell in root.iter("mxCell"):
        style = cell.get("style", "")
        if marker not in style:
            continue
        encoded = style.split(marker, 1)[1].split(";", 1)[0]
        payload = base64.b64decode(encoded, validate=True)
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Invalid embedded PNG in {path}: {cell.get('id')}")
        image_count += 1
    if image_count == 0:
        raise ValueError(f"No embedded PNG images found in {path}")


def validate_icons() -> None:
    missing = [name for name in ICON_FILES.values() if not (ICON_DIR / name).exists()]
    if missing:
        joined = ", ".join(sorted(missing))
        raise FileNotFoundError(f"Missing AWS icon assets: {joined}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=IMAGE_DIR,
        help="Directory for generated PNG and draw.io files (default: images/)",
    )
    args = parser.parse_args()

    validate_icons()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for diagram in diagram_definitions():
        render_png(diagram, args.output_dir / f"{diagram.name}.png")
        drawio_path = args.output_dir / f"{diagram.name}.drawio"
        render_drawio(diagram, drawio_path)
    render_overview_png(args.output_dir / "architecture_overview.png")


if __name__ == "__main__":
    main()
