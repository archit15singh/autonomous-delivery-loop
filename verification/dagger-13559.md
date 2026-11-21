# Dagger LLM documentation export

| In the generated artifacts | Upstream base | Candidate |
| --- | ---: | ---: |
| Canonical routes in each file | 144 | 144, same routes and order |
| Link from the index to the full corpus | Missing | Present |
| Snippet directives left in code-fence headers | 14 | 0 |
| Links to source MDX files | 230 | 0 |
| GitRepository example | Empty GraphQL include | Both GraphQL queries expanded |
| Install tabs | Raw MDX tab markup | macOS, Linux, and Windows labels next to each example |

The index and corpus now share one ordered list of canonical pages. The corpus reads Docusaurus's rendered page body, which includes expanded examples and resolved links. It derives each record's title, description, source and available date from that page's metadata.

Both revisions ran `npm exec --yes --package yarn@1.22.22 -- yarn install --frozen-lockfile` and `npm exec --yes --package yarn@1.22.22 -- yarn build` on Ubuntu 24.04 with Node 20. The candidate build also ran an independent Markdown parser over all 144 records. It counted 1,771 absolute links and 801 code fences and checked that the base route set was preserved. A fixture covered a nested base URL, an unreleased-only page, date metadata and rejection of unresolved source links.

- Base `c1f8e9ae88f6c238ee02bef12ff131847052abc2`. [Build, audit and artifacts](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44856328878)
- Candidate `cbc171fa4bdf23e63720741c679e372a0d587c74`. [Commit](https://github.com/archit15singh/dagger/commit/cbc171fa4bdf23e63720741c679e372a0d587c74) · [Build, audit and artifacts](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44857501080)
- [Upstream issue](https://github.com/dagger/dagger/issues/13559)
