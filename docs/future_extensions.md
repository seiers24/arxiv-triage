# Future extensions

Ideas in this file are deliberately outside the MVP. Each should be adopted
only when it solves a measured limitation without obscuring the core pipeline.

## How could the system expose its tools more efficiently?

Add a thin local MCP server after the reader–critic pipeline is stable. It would
expose a small set of typed operations—such as searching papers, retrieving a
paper, and querying prior analyses—while reusing the same Python functions as
the CLI scripts. The deterministic pipeline should continue calling those
functions directly; MCP is an optional interoperability adapter, not the core
architecture.
