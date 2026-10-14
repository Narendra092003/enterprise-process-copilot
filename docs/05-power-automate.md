# 05 — Power Automate Flows

Two kinds of flow:

| Flow | Purpose | Connectors |
|---|---|---|
| **A — Ingest** | SharePoint file created or changed → `POST /v1/ingestion-jobs` | SharePoint (standard), **HTTP (premium)** |
| **A2 — Delete** | SharePoint file deleted → `POST /v1/documents/delete-by-source` | SharePoint, **HTTP (premium)** |
| **B — Create Access Request** | Called by the Copilot agent after confirmation and returns the human review decision | Outlook Human review |

The **HTTP** connector is premium. Options: the Power Automate Premium trial in your tenant, or the free Power Apps **Developer Plan** environment, which includes premium connectors for development. If neither is available, skip Flow A and load documents with `scripts/ingest.py`. Flow B uses only standard connectors.

## Preparation (5 minutes)

In your SharePoint site:
1. Document library **Ops Policies**. Upload 2–3 of the files from `sample_docs/`.
2. List **Access Requests** with columns: `Title` (reference), `Resource` (text), `Role` (text), `DurationDays` (number), `Justification` (multi-line), `Requester` (text), `Status` (choice: Pending approval, Approved, Rejected).

## Flow A — Ingest new and changed documents

1. Power Automate → **Create** → **Automated cloud flow** → trigger **SharePoint – When a file is created or modified (properties only)** → Site, Library = *Ops Policies*.
2. **SharePoint – Get file content** → File Identifier = `Identifier` (dynamic content).
3. **HTTP**:
   - Method `POST`, URI `https://API_URL/v1/ingestion-jobs`
   - Headers: `Content-Type: application/json`, `X-API-Key: <admin/ingest key>`
   - Body: paste `powerautomate/flow-a-ingest-http-body.json`. The `@{...}` parts become dynamic content.
4. **Condition** `outputs('HTTP')['statusCode']` equals `202`
   - No → **Send an email (V2)** to yourself with the status code and body (alert on failure).
5. Optional: **Parse JSON** on the HTTP body (schema: `job_id`, `state`, `status_url`), then a **Do until** that calls `GET /v1/ingestion-jobs/{job_id}` every 10 seconds until `state` is `succeeded` or `failed`.
6. Settings on the HTTP action → **Retry policy**: exponential, 3 retries. The API is idempotent (same file and same content = `skipped`), so retries are safe.

Test: upload a new file to the library. Within a minute, `GET /v1/documents` (admin key) lists it, and a question about it gets an answer.

Notes:
- If the job fails with "not valid base64", change `content_base64` to `@{base64(body('Get_file_content'))}`.
- **Never put the API key in plain text in a shared flow.** For the demo it's fine. In production use an environment variable or Azure Key Vault and a service account.
- `allowed_groups` is fixed to `["all"]` here. To make it per-file, add a SharePoint choice column `AllowedGroups` and build the array with a **Compose** action: `split(triggerOutputs()?['body/AllowedGroups/Value'], ',')`.

## Flow A2 — Remove deleted documents

1. Trigger **SharePoint – When a file is deleted** → same library.
2. **HTTP** POST `https://API_URL/v1/documents/delete-by-source`, same headers, body from `powerautomate/flow-a-delete-http-body.json`.

The API marks the document `DELETED` in the catalog first (it disappears from answers instantly), then deletes its vectors.

## Earlier topic-based Flow B design

The following setup is retained as historical implementation guidance. The workflow actually used is described in [As built](#as-built) above.

## Flow B — Create Access Request (agent flow with approval)

Create it from Copilot Studio so it's connected to the agent: open the agent → **Tools** → **+ Add a tool** → **New tool** → **Agent flow**. The trigger is **When an agent calls the flow**.

1. **Trigger inputs**: `ResourceName` (Text), `Role` (Text), `DurationDays` (Number), `Justification` (Text), `RequesterEmail` (Text).
2. **Compose** `ReferenceId`: `concat('REQ-', formatDateTime(utcNow(), 'yyyyMMdd'), '-', toUpper(substring(guid(), 0, 6)))`
3. **Condition (validation)**: Role is Viewer or Contributor, DurationDays is 30/60/90, and Justification has 10+ characters (expressions in `powerautomate/flow-b-expressions.txt`).
   - No → **Respond to the agent**: `Status = rejected`, `Message = Invalid request details`. Stop.
4. **SharePoint – Create item** in *Access Requests* with `Status = Pending approval`.
5. **Respond to the agent**: outputs `Status = pending_approval`, `ReferenceId = outputs('ReferenceId')`.
   Respond **before** the approval step. The agent waits only a short time for a flow's answer, while a manager may take hours.
6. **Approvals – Start and wait for an approval**: type *Approve/Reject – First to respond*. Title: `Access request @{outputs('ReferenceId')}`. Assigned to: your manager's email (for the demo, your own). Details: resource, role, duration, justification, requester.
7. **Condition**: outcome equals `Approve`
   - Yes → **Update item** `Status = Approved` → **Send an email (V2)** to the requester: approved.
   - No → **Update item** `Status = Rejected` → email: rejected, with the approver's comments.
8. **Save** and **Publish** the flow, then use it in the `Raise access request` topic ([04](04-copilot-studio.md), step 5).

Test: confirm a request in the Copilot test panel, check that the list row appears as *Pending approval*, approve it from the Approvals email or the Teams Approvals app, and check that the row becomes *Approved*.

## Governance points to mention

- Each flow is **one fixed, named action** with validated inputs. The model can't pick a connector, URL or approver.
- Flows live in a **Solution** with **connection references** and **environment variables**, so they move cleanly from dev to test to prod.
- DLP policy: keep HTTP and business connectors in the allowed group only in the environments that need them.

## As built (October 2026)

The **CreateAccessRequest** workflow receives `Workspace`, `Role`, `DurationDays`, and `Justification`. It starts **Human review** in Outlook, configured for **First to respond**; the reviewer provides `Approved` (Yes/No) and `Comments`. **Respond to the agent** returns `ReferenceId`, `Approved`, and `ManagerComments`. The reference expression is:

```text
concat('REQ-', formatDateTime(utcNow(), 'yyyyMMdd-HHmmss'))
```

Ops Helper calls this workflow only after showing a summary of the four inputs and receiving a clear **yes**. End-to-end testing passed: the approved request returned `REQ-20261014-120744`; the no path did not call the workflow and sent no approval email. The detailed topic-based Flow B steps earlier in this guide are historical implementation guidance; the as-built agent uses Tools/Workflows.
