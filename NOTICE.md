Care Manager — Databricks Industry Solution Accelerator
Copyright (2026) Databricks, Inc.

## Support

Databricks does not offer official support for this solution accelerator or any
demo assets. It is provided as-is, best-effort, for demonstration and evaluation
only. For any issue, please open a GitHub issue and the team will review on a
best-effort basis.

## Data generation

All data in this repository is fully synthetic — there are no real patients and
no PHI. It is generated deterministically (seed=42) by the scripts in `scripts/`:

  - Structured population-health data (patients, encounters, care gaps, risk
    scores, SDOH) is generated with Mimesis and Polars.
  - Free-text clinical notes are generated at seed time via a Databricks
    Foundation Model API endpoint (Claude, called through SQL `ai_query`).

The generation code is included in this repository and can be re-run.

## Third-party components and licenses

Backend (Python):
  - databricks-sdk    Apache-2.0
  - fastapi           MIT
  - openai            Apache-2.0
  - pydantic          MIT
  - uvicorn           BSD-3-Clause
  - python-dotenv     BSD-3-Clause
  - psycopg (v3)      LGPL-3.0-only   [see note below]
  - mimesis           MIT
  - polars            MIT

Frontend (JavaScript):
  - react             MIT
  - react-dom         MIT
  - react-router-dom  MIT
  - lucide-react      ISC

Note on psycopg (LGPL-3.0): psycopg 3 is the Postgres driver used to connect to
Lakebase and is the driver Databricks' own Lakebase documentation recommends for
this OAuth-token connection pattern. It is used unmodified, as an installed
library, and is not statically linked into or redistributed as part of this
codebase. LGPL-3.0 is not among the licenses named in the FE public-content
guideline (Apache/BSD/MIT/DB); a legal/security exception is being requested on
the basis that it is the officially documented Lakebase driver. If the exception
is not granted, the driver can be swapped for a BSD-licensed alternative
(e.g. pg8000).
