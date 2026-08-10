# Proposal C: transactional outbox

Commit events to an outbox beside application state, then relay them. This preserves atomicity,
but requires relay operations and careful retention.
