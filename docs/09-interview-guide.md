# 09 — Interview Guide

## The 2-minute pitch (practise out loud)

> "Employees kept asking operations the same questions: how to get access to a tool, the leave rules, expense limits, VPN fixes. The answers existed, but they were spread across policy documents. I built an internal assistant in **Copilot Studio** that answers these questions **only from approved documents, with a citation**, and can start routine requests through **Power Automate**.
>
> The core is a **Python FastAPI** service. It parses PDFs and Word files, chunks them by section, embeds them, and stores them in **Pinecone** with metadata such as allowed groups, version and status. When a question comes in, it goes through **safety filters** (prompt-injection blocking, PII redaction), then a vector search with a **server-side access filter**, and then a re-check against the document catalog. If the best match is below a threshold I calibrated on a labelled question set, the assistant says it doesn't know instead of guessing.
>
> Copilot Studio calls the API through the AskCompanyDocs workflow. An access request only runs after the user confirms, then goes through human review in Outlook. On the measured evaluation set it got **27/27** answerable questions right at hit@1, abstained on **4/4** unanswerable questions, and leaked **0** restricted documents."

See [the recorded evaluation](EVALUATION.md) for the measurements and their limits.

## Whiteboard it in 5 boxes

`User → Copilot Studio → FastAPI (auth → safety → embed → Pinecone filter → catalog re-check → threshold) → evidence → Copilot answer`
Below: `SharePoint → Flow A → /v1/ingestion-jobs → parse → chunk → scan → embed → upsert`
Side: `Copilot → confirm → Flow B → approval → list row`

## Likely questions and strong answers

**Why RAG and not fine-tuning?**
Policies change often and need citations. With RAG, an update is a re-index, not a retraining, and every answer points to a source. Fine-tuning can't easily delete a policy or prove where an answer came from.

**Why Pinecone?**
It was the required stack, and it's a managed serverless vector database with metadata filtering, which I use for access control. I don't treat it as the system of record: the SQLite catalog decides what is live.

**How do you chunk, and why?**
By headings and paragraphs, about 180 words with 30 words of overlap, keeping the section title with the chunk. Policies are written in sections, so one chunk usually equals one rule or one procedure, and citations read naturally. The size is a setting I'd tune with the evaluation set.

**Which embedding model? What dimension?**
Pinecone-hosted `multilingual-e5-large`, 1024 dimensions, cosine. e5 uses different input types for queries and passages. The index dimension must match the model; my code refuses to start on a mismatch, and changing models means a new index.

**How do you stop users seeing documents they shouldn't?**
Three layers. (1) Identity comes from the API key on the server, and the request schema rejects fields like `user_id` or `groups`. (2) The server builds the Pinecone metadata filter: allowed groups, ACTIVE status, not flagged. (3) Every hit is re-checked against the catalog before anything is returned. A test asserts that an employee asking about the HR-only document gets nothing, not even its title.

**What is prompt injection, and how do you handle it?**
Text that tries to make the model ignore its rules, either typed by the user or hidden inside a document. I block known patterns in queries, flag document chunks with instruction-like text at ingestion and never return them, and the agent instructions say to treat documents as data. Honestly, regex is a weak signal on its own. The real protection is that retrieval can't trigger actions, actions need explicit user confirmation, and access is enforced in code, not in the prompt.

**How do you prevent hallucination?**
The API returns evidence, not free text. If the top score is below a calibrated threshold, it abstains and routes to the service desk. The agent instructions require a citation for every claim. I measure abstention accuracy on unanswerable questions.

**How did you choose the threshold?**
`evaluate.py --calibrate` prints the top score for answerable and unanswerable questions. I chose a value between the two ranges and favoured abstaining over answering wrongly, since a wrong policy answer costs more than "please ask the service desk".

**What happens when a document is updated or deleted?**
Ingestion is idempotent: same source and same content hash means skip. A new version gets new vector IDs; once they're written, the old version's vectors are deleted. Delete marks the document DELETED in the catalog first, so it's hidden instantly even if vector cleanup fails.

**Why Power Automate, not Python, for the actions?**
Business teams own approvals and connectors in Power Platform, with DLP policies, audit and the Approvals app. Python owns retrieval and security. Each flow is one named action with validated inputs, so the model can't call arbitrary endpoints.

**How does Copilot Studio call your API?**
The Ops Helper agent calls the AskCompanyDocs workflow, which accepts a `Question`, sends it to `/v1/answer` with an HTTP POST, and returns `Answer`, `Status`, and `SuggestedAction` to the agent. The current Copilot Studio interface uses Tools/Workflows; the topic-based example in `copilot/knowledge-topic.yaml` is a legacy reference.

**What are "context-aware response templates"?**
The API classifies the question as how-to, policy, troubleshooting or contact, picks the passage that fits (for example one with numbered steps for a how-to), and fills a fixed template: answer, source and next step. Blocked, no-evidence and low-confidence cases have their own safe templates. If the document is linked to an action, it offers that action.

**How do you measure success / "reduced manual effort"?**
`/v1/metrics` gives the self-service rate (questions answered with a citation), abstentions, blocked attempts, latency, and helpful/not-helpful feedback. In a real pilot I'd compare service-desk tickets in those categories before and after.

**What would you change for production?**
Entra ID tokens instead of API keys, with groups from token claims; SharePoint permissions synced through Microsoft Graph; PostgreSQL and a durable queue (Service Bus) instead of SQLite and background tasks; Key Vault for secrets; Application Insights; malware scanning and OCR; hybrid search with a reranker if the evaluation shows a gain.

**Biggest challenge?**
Pick a real one from your build week, for example calibrating the threshold when answerable and unanswerable scores overlapped, Copilot Studio's response schema mapping, or the Power Automate base64 file content. Interviewers trust specific stories.

**Did you use AI to build this?**
Be honest: "Yes, I used an AI coding assistant, like most engineers now. I defined the architecture and safety rules, built it phase by phase, reviewed and tested every part, and measured the results myself. I can walk you through any file." Then prove it by explaining a file without notes. Don't claim you wrote every line by hand, and don't hide the assistant.

**What if Pinecone is down?**
`/health/ready` reports not ready, and the search returns an error that Copilot turns into "please try again or contact the service desk". It never falls back to answering from general knowledge.

## Resume bullets that are true for this build

These bullets describe the measured build:

- Built an internal process assistant with **Microsoft Copilot Studio** and a **Python/FastAPI** retrieval API, answering employee policy and IT questions from approved documents with source citations and safe "not found" fallbacks.
- Indexed synthetic policy and process documents into **Pinecone** with section-aware chunking and group-based metadata filters; reached **100% hit@1** on 27 answerable questions with **0** restricted-document leaks.
- Implemented prompt-safety filters (injection blocking, PII redaction, poisoned-document flagging) and intent-based response templates, and automated access requests through **Power Automate** with user confirmation and manager approval.

Avoid claiming a production deployment, real users, or a percentage reduction in manual work unless you measured it. "Designed to reduce manual query handling, measured by self-service rate" is honest and still strong.

## 10-minute self-test (night before)

Without looking at the code, explain: what `_filter()` returns; why there is a catalog re-check after Pinecone; what `MIN_SCORE` does; why `extra="forbid"` is on the request models; what happens to a chunk containing "ignore previous instructions"; why Flow B responds to the agent before waiting for approval.
