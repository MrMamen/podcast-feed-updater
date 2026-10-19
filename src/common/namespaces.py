"""XML namespaces used in podcast feeds."""

PODCAST_NS = "https://podcastindex.org/namespace/1.0"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
PSC_NS = "http://podlove.org/simple-chapters"
ATOM_NS = "http://www.w3.org/2005/Atom"

# Prefixes for lxml tag names: f"{PODCAST}person" == "{https://podcastindex.org/namespace/1.0}person"
PODCAST = f"{{{PODCAST_NS}}}"
ITUNES = f"{{{ITUNES_NS}}}"
CONTENT = f"{{{CONTENT_NS}}}"
PSC = f"{{{PSC_NS}}}"
ATOM = f"{{{ATOM_NS}}}"
