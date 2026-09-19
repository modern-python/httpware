# `*_with_response` is a separate method family, and pagination is a recipe over it

Returning `(response, decoded)` is `send_with_response` plus per-verb siblings, not a
`with_response=True` flag on `send`, because a flag-driven return type hides the shape at the call
site, in tracebacks, and in grep. `head` and `options` have no sibling since a typed body from them
is not a real case. No `paginate()` helper ships: Link headers, body cursors, page numbers, and
opaque `next` URLs would need a configuration object the size of a library, and blessing one form
makes the others look unsupported, while `send_with_response` already hands a caller's loop
everything atomically.
