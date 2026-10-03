# Direct orchestrator web research

The conversational orchestrator offers `web_search` and `web_fetch` alongside its
project file tools. No project or worker task is required. Ordinary provider tasks
retain their existing tools; this change adds browsing to the orchestrator itself.

- `web_search(query)` uses the existing Gemini connection with Google Search grounding,
  even when another model is selected for orchestrator conversation. Its backend is
  disclosed in the tool definition and capability catalog. Search is not offered
  without configured Gemini credentials. Remote access/model eligibility is checked
  on execution; no new account or subscription is provisioned.
- `web_fetch(url, offset, limit)` reads public HTTPS HTML/text/JSON directly. Results
  contain the final source URL, title, text page, links, retrieval timestamp and raw
  response hash. Pagination reuses the same fetched version during that conversation
  turn. A later turn fetches fresh evidence.

The shared conversation loop allows 12 tool calls in six rounds. Within that budget,
web research permits two grounded-search API requests and six page downloads. A
grounded request can execute multiple Google search queries; the local limit is not
a search-query or billing cap. Existing provider usage/pricing applies. Pages are
limited to 1 MB and 24,000 returned characters per call. Redirects are bounded, and
each destination must resolve exclusively to public addresses. The connection is
pinned to a checked IP while TLS still verifies the original hostname. No cookies,
authorization headers, proxy credentials or private-network access are supplied.

The reader does not execute JavaScript, log in, click controls, submit forms or decode
PDF/media pages. Unsupported types, HTTP failures, missing search grounding and read
limits return explicit errors. A search submission with an uncertain outcome blocks
further search attempts that turn; it is not automatically retried or switched to
another provider. Normal chat recovery continues to protect uncertain submissions.

Search output is identified as model-generated synthesis with grounding sources;
it is not presented as fetched page text. The orchestrator is instructed to read
primary pages for precise claims and cite source links. Public content remains
untrusted research material, not new instructions or authorization.

Per-turn requests/results are journaled under `private/orchestrator-reads/`. Search
responses retain their original grounding metadata; fetched text retains its source
hash and retrieval time. A turn using search produces one HTML source report attached
to the answer, including source links and the Google Search suggestions widget in a
sandboxed frame. Telegram cannot render that widget inline; open the attached HTML
document to inspect it. Simple page reads do not add an extra document.

Conversational browsing does not import research into a production or change a
frozen worker assignment. A separate registered production operation,
`web.sources`, can submit 1–20 explicit public text queries in a reviewed plan.
It uses the configured Gemini text model for grounded search; Google may rewrite
the effective search terms. Relay attempts the first two grounded links per query
and reads public HTML/text pages when accessible. Optional domain filters restrict
source hosts. A failed fetch or an off-target first link can leave an article
unresolved even when another public catalog page exists.
The exact `delivery/source-pack.json` contains query terms, grounded candidate
URLs, fetched text with raw response hashes and timestamps, and explicit gaps.
Search hits are candidates, not verified facts or exact OEM matches. A downstream
file worker must consume the declared source pack, and an independent reviewer
checks the matches. The operation neither signs in nor reads PDF/JavaScript sites.
It has controlled tests and is installed locally in 0.13.94; no live source
coverage is claimed.

Examples:

- “Search online for the original ReAct paper, read its abstract, and explain it.”
- “Read https://example.com/ and summarize the page.”
- “Find current primary sources on these products and cite each comparison.”

API reference: [Google Search grounding](https://ai.google.dev/gemini-api/docs/generate-content/google-search).
