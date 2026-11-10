# Understand parity fixture

This tree is scanned by both the Python graph producer and the Go adapter. Keep
it deterministic and small: the test compares normalized file records and graph
deltas, not prose.
