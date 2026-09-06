# No pagination helper

**Decision:** httpware ships no `paginate(...)` iterator. Link-header pagination is documented as
a recipe the caller writes, over `send_with_response`.

Pagination is the dominant use for `send_with_response`, which makes a helper look like the
obvious next step. It is not, because a generic helper cannot avoid making the caller's choices
for them: RFC 8288 `Link` headers, a cursor in the body, a page number in the query string, an
opaque `next` URL, and an envelope-with-total are all in wide use, and a signature that covers
them is a configuration object big enough to be its own library. Picking only `Link` headers is
the narrow version of the same problem — it would be the one form httpware blesses, and every
other API would look unsupported.

The shape that generalises is the one already shipped: `send_with_response` returns the response
and the decoded body together, atomically, so the caller's own loop has everything it needs.
`docs/recipes/link-header-pagination.md` is roughly ten lines and is honest about the
caller-supplied `Link` parser.

**Revisit trigger:** a pagination form that `send_with_response` provably cannot express, rather
than one it merely does not sugar.
