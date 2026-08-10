# Proposal A: synchronous writes

Write every event directly to Postgres. This is simplest and provides immediate consistency,
but request latency and database availability remain coupled.
