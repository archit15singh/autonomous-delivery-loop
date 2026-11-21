import argparse
import re
from pathlib import Path
from urllib.parse import urlsplit


parser = argparse.ArgumentParser(description="Measure Dagger's generated LLM docs")
parser.add_argument("index", type=Path)
parser.add_argument("corpus", type=Path)
args = parser.parse_args()
index = args.index.read_text(encoding="utf-8")
corpus = args.corpus.read_text(encoding="utf-8")

index_links = re.findall(r"^- \[[^\n]+?\]\(([^)\s]+)\)", index, re.MULTILINE)
routes = set(index_links)
corpus_routes = set(re.findall(r"^URL: (\S+)", corpus, re.MULTILINE))
snippet_directives = re.findall(r"^`{3,}[^\n]*\bfile=\S+", corpus, re.MULTILINE)
source_links = re.findall(r"\]\(([^)\s]+\.mdx(?:#[^)\s]+)?)\)", corpus)

assert index_links and corpus_routes, "Expected both exports to contain documentation"
print(f"index_links={len(index_links)}")
print(f"relative_index_links={sum(not urlsplit(link).scheme for link in index_links)}")
print(f"corpus_pointer={'llms-full.txt' in index}")
print(f"corpus_records={len(corpus_routes)}")
print(f"index_only_routes={len(routes - corpus_routes)}")
print(f"corpus_only_routes={len(corpus_routes - routes)}")
print(f"snippet_directives={len(snippet_directives)}")
print(f"source_mdx_links={len(source_links)}")
for label, entries in (("index only", routes - corpus_routes), ("corpus only", corpus_routes - routes)):
    for entry in sorted(entries)[:5]:
        print(f"{label}: {entry}")
for directive in snippet_directives[:3]:
    print(f"snippet: {directive}")
