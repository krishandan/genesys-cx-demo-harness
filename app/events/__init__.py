"""Events: interaction history, CSAT write-back, and the telemetry seam.

One generic table. An event is a `kind` string plus a JSONB `payload`, so a new event
kind is data, never a migration or a new table. gx responses over events stay flat by
projecting the payload into scalar fields at the boundary.
"""
