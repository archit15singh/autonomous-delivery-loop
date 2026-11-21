import argparse
from hashlib import sha256
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

parser = argparse.ArgumentParser()
parser.add_argument("index", type=Path)
parser.add_argument("corpus", type=Path)
parser.add_argument("expected_routes_digest")
args = parser.parse_args()
index = args.index.read_text(encoding="utf-8")
corpus = args.corpus.read_text(encoding="utf-8")
markdown = MarkdownIt("commonmark")


def link_targets(tokens):
    return [
        child.attrGet("href" if child.type == "link_open" else "src")
        for token in tokens
        for child in token.children or []
        if child.type in ("link_open", "image")
    ]


intro, docs_index = index.split("\n## Docs\n", 1)
introduction_links = link_targets(markdown.parse(intro))
assert len(introduction_links) == 1
assert urlsplit(introduction_links[0]).scheme == "https"
assert urlsplit(introduction_links[0]).path == "/llms-full.txt"
index_routes = link_targets(markdown.parse(docs_index))

record_pattern = re.compile(
    r"^---\ntitle: (.+)\ndescription: (.+)\nsource: (\S+)"
    r"(?:\nlast_updated: (\d{4}-\d{2}-\d{2}))?\n\n", re.MULTILINE
)
records = list(record_pattern.finditer(corpus))
assert records and records[0].start() == 0
corpus_routes = [record[3] for record in records]
assert len(index_routes) == len(set(index_routes)) == 144
assert corpus_routes == index_routes, "Index and corpus order or route set diverged"
digest = sha256("\n".join(sorted(corpus_routes)).encode()).hexdigest()
assert digest == args.expected_routes_digest, "Public route set changed from the pinned baseline"

count_links = count_fences = 0
directory_languages = set()
git_repository_queries = False
for i, record in enumerate(records):
    assert json.loads(record[1]), f"Missing title at {record[3]}"
    assert isinstance(json.loads(record[2]), str), f"Invalid description at {record[3]}"
    source = urlsplit(record[3])
    assert source.scheme == "https" and source.netloc == "docs.dagger.io"
    end = records[i + 1].start() if i + 1 < len(records) else len(corpus)
    body = corpus[record.end():end]
    assert body.strip(), f"Empty doc body at {record[3]}"
    tokens = markdown.parse(body)
    for link in link_targets(tokens):
        url = urlsplit(link)
        assert url.scheme, f"Relative link at {record[3]}: {link}"
        assert not unquote(url.path).lower().endswith(".mdx"), f"Source link at {record[3]}: {link}"
        count_links += 1
    for token in tokens:
        if token.type != "fence":
            continue
        assert not re.search(r"\bfile=\S+", token.info), f"Unexpanded snippet at {record[3]}"
        count_fences += 1
        if source.path == "/reference/api/directory":
            directory_languages.add(token.info)
        if source.path == "/reference/api/git-repository" and token.info == "graphql":
            git_repository_queries |= all(
                query in token.content for query in ("query CurrentCommit {", "query InDefaultBranch(")
            )

assert git_repository_queries, "Previously unexpanded GraphQL example is still missing"
assert {"go", "python", "typescript"} <= directory_languages, directory_languages
print(f"routes={len(records)} exact_base_route_digest={digest} ordered_match=true")
print(f"pointer={introduction_links[0]}")
print(f"absolute_corpus_links={count_links} source_mdx_links=0 relative_links=0")
print(f"code_fences={count_fences} snippet_directives=0 git_repository_graphql_queries=true")
print(f"directory_languages={','.join(sorted(directory_languages))}")
