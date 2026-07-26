# Stage G raw-tensor isolation

This directory is intentionally separate from the production inference path.

`locked_case.json` identifies the only image and the only input byte stream
allowed in the Stage G comparison.  Historical input variants under `data/`
are excluded.  The reference and current runners must both read
`data/test_input.nv12` directly, dump every model output before decode or NMS,
and leave the production pipeline unchanged.
