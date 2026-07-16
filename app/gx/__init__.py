"""gx: the flat, contract-safe surface Genesys binds to.

Two rules hold everywhere under this package:

1. Responses are flat. No nested arrays, because Genesys data action output contracts
   cannot express them. An array of flat objects at the top level is fine.
2. This is where real-world messiness is absorbed. /v1 stays a faithful low-level view;
   gx normalizes what Genesys actually sends.
"""
