"""
Attach the XSL stylesheet that renders feeds as HTML when opened in a browser.

The stylesheet source lives in assets/feed.xsl and is copied next to each
written feed so the relative href resolves on GitHub Pages. Podcast apps
ignore the xml-stylesheet processing instruction.
"""

import shutil
from pathlib import Path

from lxml import etree

STYLESHEET_NAME = 'feed.xsl'
STYLESHEET_SOURCE = Path(__file__).resolve().parents[2] / 'assets' / STYLESHEET_NAME


def attach_stylesheet_pi(root: etree._Element) -> None:
    """Add the xml-stylesheet processing instruction before the root element.

    Does nothing if one is already present (e.g. when re-processing a feed
    written by this project, as the YouTube variant does with --local-cache).
    """
    sibling = root.getprevious()
    while sibling is not None:
        if isinstance(sibling, etree._ProcessingInstruction) and sibling.target == 'xml-stylesheet':
            return
        sibling = sibling.getprevious()

    root.addprevious(etree.ProcessingInstruction(
        'xml-stylesheet', f'type="text/xsl" href="{STYLESHEET_NAME}"'
    ))


def copy_stylesheet(output_file: str) -> None:
    """Copy feed.xsl into the directory of ``output_file`` so it gets deployed."""
    if STYLESHEET_SOURCE.is_file():
        shutil.copyfile(STYLESHEET_SOURCE, Path(output_file).resolve().parent / STYLESHEET_NAME)
