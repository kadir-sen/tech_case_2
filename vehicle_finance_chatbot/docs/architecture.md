# Architecture

## 1. Sistem Görünümü

```mermaid
flowchart LR
    MOB[Mobile Banking App] -->|X-Customer-Id| BFF[BFF / API Gateway]
    BFF -->|POST /chat/session| API[FastAPI]
    BFF -->|POST /chat + edited_fields| API
    API --> GREET[greeting_node<br/>template: ad + gender → 'Bey/Hanım']
    API --> ORCH[LangGraph Orchestrator]
    ORCH --> EXT[LLM Intent + Field Extractor<br/>Pydantic structured output]
    ORCH --> RAG[FAQ Retriever<br/>FAISS / Qdrant + RAG]
    ORCH --> RULES[Deterministic Rules<br/>rules.py limit/oran/kefil]
    ORCH --> RESP[Response Generation<br/>validation → doğal Türkçe]
    ORCH --> FUZZ[rapidfuzz vehicle catalog]
    ORCH --> SEC[Guardrails + PII Mask]
    ORCH --> DB[(SQLAlchemy)]
    EXT --> GW[LiteLLM Gateway<br/>routing + budget + customer quota]
    RESP --> GW
    GW --> LLM[(vLLM / Ollama<br/>OpenAI-compatible)]
    DB --> AUD[(audit_logs)]
    DB --> APP[(vehicle_finance_applications)]
    DB --> CONV[(conversation_states)]
    DB --> HGS[(hgs_leads)]
    DB --> USE[(llm_usage_logs<br/>customer abuse tracking)]
```

## 2. LangGraph Workflow (per turn)

```mermaid
flowchart TD
    START([START]) --> LS[load_session_context]
    LS --> GR[guardrail]
    GR -->|blocked| END([END w/ safe reply])
    GR --> INT[intent_node]
    INT --> RI[route_intent]
    RI -->|FAQ| FAQ[faq_router_node] --> END
    RI -->|CANCEL| C[cancel] --> END
    RI -->|HGS decision| HD[hgs_decision_node] --> END
    RI -->|CONFIRM @AWAITING_CONFIRMATION| P[persistence_node]
    RI --> AF[field_extraction_node]
    AF --> V[validation_node]
    V -->|missing fields| COL[collection_node] --> END
    V -->|errors| END[end w/ fix prompt]
    V -->|valid| S[summary_node] --> END
    P --> HO[hgs_offer_node] --> END
```

Bütün yollar **tek bir reply** üretir. Her turn'de graph baştan çalışır;
state `ConversationRepository` üzerinden persist edilir.

## 3. Data Flow

1. Mobile app `X-Customer-Id` header'ı ile `POST /chat` yapar.
2. `require_customer` mock customer store'dan profili çeker.
3. `ConversationRepository.load` ile geçmiş state yüklenir.
4. `GraphState` oluşturulur ve LangGraph çalıştırılır.
5. Reply + actions kullanıcıya döner; state persist edilir.

## 4. Security Layer

```mermaid
flowchart LR
    USER[User msg] --> IG[Input Guardrail<br/>prompt injection patterns]
    IG -->|blocked| SAFE[Safe reply]
    IG --> LLM[LLM extraction]
    LLM --> SCHEMA[Pydantic schema validation]
    SCHEMA --> RULES[Deterministic rules]
    RULES --> RESP[Response builder]
    DOC[RAG chunks] --> OG[Context guardrail<br/>strip injection lines]
    OG --> LLMFAQ[LLM faq answer]
    RESP --> PII[PII masking on logs]
    PII --> AUDIT[audit_logs]
```

## 5. RAG Flow

```mermaid
flowchart LR
    FAQ[vehicle_finance_faq.md] --> CHUNK[chunk_markdown]
    CHUNK --> EMB[HashEmbedder<br/>or SentenceTransformer]
    EMB --> STORE[(InMemoryVectorStore<br/>FAISS / Qdrant)]
    Q[User question<br/>intent=FAQ_QUESTION] --> RET[FaqRetriever.search]
    STORE --> RET
    RET --> CTX[Context guardrail filter]
    CTX --> ANS[LLM answer<br/>or top-chunk fallback]
```

## 6. LLM Gateway (LiteLLM)

```mermaid
flowchart LR
    NODE[LangGraph node<br/>node_purpose=...] --> GW[LLMGatewayClient]
    GW --> POL[routing_policy<br/>NodePolicy]
    GW --> BUD[budget.fit_to_budget<br/>trim or fail]
    BUD -->|over budget| SAFE[Safe deterministic reply]
    GW --> LITELLM[LiteLLM Proxy :4000]
    LITELLM --> VLLMLARGE[vLLM 72B :8000]
    LITELLM --> VLLMSMALL[vLLM 14B :8001]
    LITELLM --> GUARD[Llama-Guard :8002]
    LITELLM --> OLLAMA[Ollama :11434 dev]
    LITELLM -. blocked by default .-> CLOUD[OpenAI cloud fallback]
    GW --> USAGE[(llm_usage_logs<br/>PII-free)]
    GW -->|policy.fallback_alias| LITELLM
```

Application kod hiçbir model ID'sini bilmez; sadece `vehicle-finance-{small,large,guard}` alias'ları üzerinden iletişim kurar. Model swap = `infra/litellm/config.yaml` değişikliği + LiteLLM restart.

Cloud fallback **kod seviyesinde** kapatılmıştır (`_CLOUD_ALIASES` setine erken redaksiyon). Yalnızca `ENABLE_CLOUD_FALLBACK=true` env ile açılabilir; PII redaction adımı henüz tamamlanmadığı için MVP'de devre dışı kalmalı.

## 7. Production-grade Notları

- **Vehicle catalog**: `domain/vehicle_catalog.py` MVP mock'tur. Prod'da
  bankanın **kasko değer listesi** veya **araç model katalog** servisi
  ile değiştirilir. Binek/ticari ayrımı LLM ya da regex ile değil,
  servisin döndüğü model sınıfı üzerinden yapılır.
- **Conversation state**: bu MVP'de tek-row JSON tutuluyor. Prod'da
  LangGraph checkpointer'ı PostgreSQL'e bağlanmalı, history dedicated
  tabloya alınmalı.
- **TCKN**: stored masked. Prod'da `SecretStore` arkasına KMS/HSM bağlanıp
  encrypted at-rest tutulur. Anahtar rotasyonu ve audit'i ayrı politika.
- **Auth**: header tabanlı mock. Prod'da BFF imzalı JWT veya mTLS ile
  oturum kanıtı sunmalı; chat servisi customer-master üzerinden profili
  doğrulamalı.
- **Observability**: Langfuse veya LangSmith ile per-turn tracing,
  Prometheus ile latency / hata oranı metrikleri, Grafana paneli.
