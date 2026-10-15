"""Render policies and template pages to printable HTML, then to PDF and PNG with Chromium."""

import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt
from playwright.sync_api import Page, ViewportSize, sync_playwright
from pypdf import PdfReader

from policy_builder.schema import Policy

PRINTABLE_HEIGHT_PX = 10 * 96  # Letter height minus 0.5in top and bottom margins, at 96 CSS px per inch
PAGE_VIEWPORT = ViewportSize(width=816, height=1056)  # Letter at 96 CSS px per inch

env = Environment(loader=PackageLoader("policy_builder"), autoescape=select_autoescape())
CSS = files("policy_builder").joinpath("templates/page.css").read_text()


@dataclass
class Printed:
    pages: int
    content_height_px: float

    @property
    def page_fill(self) -> float:
        """How much of one printable page the content uses; above 1.0 it spills onto a second page."""
        return round(self.content_height_px / PRINTABLE_HEIGHT_PX, 2)


def policy_html(policy: Policy) -> str:
    return env.get_template("policy.html.j2").render(p=policy, css=CSS)


def markdown_html(markdown_path: Path, title: str) -> str:
    body = MarkdownIt("commonmark").render(markdown_path.read_text())
    return env.get_template("doc.html.j2").render(title=title, body=body, css=CSS)


def print_page(html_path: Path, pdf_path: Path, png_path: Path) -> Printed:
    """Print to Letter PDF and screenshot. Set CHROMIUM_PATH to use a Chromium other than Playwright's own."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH"))
        printed = print_with(browser.new_page(viewport=PAGE_VIEWPORT), html_path, pdf_path, png_path)
        browser.close()
    return printed


def print_with(page: Page, html_path: Path, pdf_path: Path, png_path: Path) -> Printed:
    page.goto(html_path.resolve().as_uri())
    page.emulate_media(media="print")
    content_height = page.eval_on_selector(".sheet", "el => el.getBoundingClientRect().height")
    page.pdf(path=str(pdf_path), prefer_css_page_size=True, print_background=True)
    page.emulate_media(media="screen")
    page.screenshot(path=str(png_path), full_page=True)
    page.close()
    return Printed(pages=len(PdfReader(pdf_path).pages), content_height_px=content_height)
