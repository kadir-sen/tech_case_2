# Vehicle Finance Chatbot — Production-Style MVP

Bir bankanın mobil uygulaması içinde çalışan **taşıt finansmanı ön başvuru
asistanı**. Müşteri mobil bankacılıkta zaten authenticated olduğu için
kimlik bilgileri tekrar sorulmaz; chatbot yalnızca başvuruyu tamamlamak
için eksik bilgileri toplar.

Bu repo serbest sohbet eden bir bot değildir. Amaç **bankacılık
disiplini**ne uyan, **deterministic validation**, **RAG destekli FAQ**,
**LangGraph tabanlı stateful workflow**, **local LLM uyumu**,
**guardrail**, **idempotency** ve **audit logging** içeren bir
transactional assistant geliştirmektir.

---

## 1. Mimari Özet

```
mobile app -> Chat API (FastAPI)
                |
                v
        LangGraph workflow
        (one turn = one path)
                |
   +------------+------------+------------+--------------+
   |            |            |            |              |
guardrail   intent /        RAG /         idempotent     audit +
filter      structured      FAQ           DB write       PII
            extractor       retriever     (SQLAlchemy)   masking
                |
                v
    deterministic rules engine
    (NEW / USED validators)
```

Detaylı diagram için [docs/architecture.md](docs/architecture.md).

### Yapı Taşı Kararları (özet)

- **LLM-first konuşma, deterministic kurallar.** Niyet anlama,
  alan çıkarımı, greeting üretimi, validation hata mesajı yumuşatma ve
  FAQ cevabı LLM ile yapılır. Limit / kefil zorunluluğu / yaş üst sınırı /
  ticari kontrol / TCKN checksum / idempotency / DB yazımı tamamen
  `app/domain/rules.py` ve `app/security/*` içinde **deterministic kod**
  olarak kalır — LLM bu sayıları üretmez, yalnızca müşteriye iletir.
- **vLLM / Ollama on-prem inference.** 96 GB GPU (2×48) ile Qwen2.5-72B-AWQ
  large alias, 14B small alias. LiteLLM gateway tüm çağrıları yönlendirir,
  per-node token budget enforce eder, customer-bazlı sliding-window
  kullanım kontrolü yapar.
- **Test & demo için stub extractor.** Production yolu yalnızca
  `LLMExtractor`. CI'da ve `scripts/demo_conversation.py` içinde
  `app/chatbot/chains/dev_extractor.py:StubExtractor` keyword-based
  deterministic akış yürütür — gerçek LLM olmadan end-to-end test edilebilir.
- **Auth context dışarıdan.** `X-Customer-Id` header'ı BFF'den gelir;
  müşteri profili mock store'da. Production'da bu auth katmanı bankanın
  customer-master servisine bağlanır. KVKK açık rızası mobil bankacılık
  login adımında sözleşmesel olarak alınır; chatbot içinde tekrar bir
  rıza adımı yoktur.
- **State JSON olarak persisted.** `ConversationStateModel` her turn'de
  yüklenir/kaydedilir; resume akışı destekler.
- **Idempotency.** Aynı session + idempotency_key (veya default
  `session_id:confirm`) tekrar geldiğinde aynı başvuru ID'si döner;
  duplicate row yazılmaz.
- **Guardrails.** Prompt injection pattern'leri yakalanır; RAG
  context'ine sızabilecek talimat satırları temizlenir; LLM tool çağrı
  isimleri allowlist'tedir.

---

## 2. Hızlı Başlangıç (Local)

```bash
cd vehicle_finance_chatbot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Production için LLM_GATEWAY_ENABLED=true + LiteLLM proxy gerekli.
# Test/demo akışı için stub extractor monkey-patch ile gerçek LLM olmadan koşar.
uvicorn app.main:app --reload --port 8080
```

Sağlık kontrolü:

```bash
curl http://localhost:8080/health
```

### Docker ile

```bash
docker compose up --build
```

`docker-compose.yml` içinde Qdrant ve isteğe bağlı vLLM servisi
tanımlıdır.

---

## 3. LLM Bağlama

### vLLM (önerilen prod yolu)

vLLM, OpenAI-compatible bir HTTP server sunar. 2x48 GB GPU ile
quantized 70B/72B sınıfı modeller (örn. `Qwen2.5-72B-Instruct-AWQ`)
makul latency'de çalışır.

```bash
pip install vllm
vllm serve Qwen/Qwen2.5-72B-Instruct-AWQ \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 \
  --max-model-len 8192
```

`.env`:

```env
LLM_PROVIDER=vllm
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=Qwen2.5-72B-Instruct-AWQ
LLM_TEMPERATURE=0.1
```

### Ollama (geliştirme yolu)

```bash
ollama pull qwen2.5:14b-instruct
ollama serve
```

`.env`:

```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:14b-instruct
```

### Stub (test/CI/demo)

Production yolu yalnızca `LLMExtractor`. CI ve demo için
`app/chatbot/chains/dev_extractor.py:StubExtractor` deterministic akış
yürütür. `tests/conftest.py` ve `scripts/demo_conversation.py` modülü
monkey-patch ile bağlar — gerçek LLM olmadan tüm testler ve evaller
100% geçer.

### Model Seçim Kriterleri

Bu MVP'de tek bir model seçimi dayatılmadı — kararı benchmark'a
bırakıyoruz:

- Türkçe anlama ve üretim kalitesi
- Structured / JSON çıktı başarısı (intent extraction kritik)
- Tool calling uyumu
- Hallucination oranı, özellikle finansal limit sorularında
- GPU bellek tüketimi (96 GB ile 70B AWQ rahat sığar)
- Latency hedefi (TT-FT < 1.5 sn, full reply < 3 sn)
- Concurrent kullanıcı kapasitesi
- Lisans uygunluğu

### 2×48 GB GPU İçin Önerilen Model Stratejisi

Case'in sağladığı 2×48 GB = 96 GB GPU bütçesi göz önüne alındığında:

| Yaklaşım | Model | Yaklaşık VRAM | Notlar |
|---------|-------|---------------|--------|
| **Tek büyük model** | Qwen2.5-72B-Instruct-AWQ (4-bit) | ~42–48 GB | TP=2 ile rahat, structured output güçlü, Türkçe iyi |
| Tek büyük model (alt.) | Llama-3.3-70B-Instruct-AWQ | ~42 GB | Genel reasoning iyi, JSON için biraz daha az sağlam |
| **Hibrit** | Qwen2.5-32B-Instruct (FP16) | ~64 GB | Daha düşük latency, yüksek concurrency |
| Hibrit + Guardrail | Qwen2.5-14B + Llama-Guard-3-8B | ~28 GB + 16 GB | Ayrı guardrail process, ana modeli serbest bırakır |
| Düşük latency | Qwen2.5-7B-Instruct (FP16) | ~14 GB | Form filling yeterli, FAQ için biraz zayıf |

Öneri: **MVP → Qwen2.5-14B/32B**, **prod → Qwen2.5-72B-AWQ veya Llama-3.3-70B-AWQ**. Türkçe için Trendyol-LLM-7B veya Turkcell-LLM gibi domain modelleri yardımcı olabilir; ama Qwen2.5/Llama-3.3 ailesi case'i karşılayacak kadar Türkçe.

---

## 4. API

### Tipik akış

```bash
# Turn 0 — chatbot açılır, greeting üretilir
curl -X POST http://localhost:8080/chat/session \
  -H "X-Customer-Id: CUST001"
# → {"session_id":"sess-abc...", "reply":"Merhaba Ayşe Hanım, taşıt finansmanı...", ...}

# Turn 1 — başvuru
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Id: CUST001" \
  -d '{
    "session_id":"sess-abc...",
    "message":"Yeni araç için başvuru yapacağım. Toyota Corolla, fatura 4 milyon, 2 milyon finansman istiyorum.",
    "idempotency_key":"msg-1"
  }'

# Turn 2 — kullanıcı özet tablosunda finansmanı düzeltip onayladı
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Id: CUST001" \
  -d '{
    "session_id":"sess-abc...",
    "message":"confirm",
    "edited_fields": {"requested_amount": 1700000},
    "idempotency_key":"confirm-1"
  }'

# Başvuruya bak
curl -H "X-Customer-Id: CUST001" \
  http://localhost:8080/applications/APP-XXXXXXXXXXXX

# Müşteri kullanım izleme (suspicious abuse erken uyarı)
curl -H "X-Customer-Id: CUST001" \
  http://localhost:8080/admin/customer-token-usage/CUST001
```

### Diğer endpointler

- `GET /health`
- `POST /chat/session` — chatbot açıldığında çağrılır, greeting üretir
- `GET /sessions/{session_id}` — persisted conversation state
- `POST /rag/ingest` — opsiyonel; FAQ dokümanını yeniden yükler
- `GET /admin/customer-token-usage/{customer_id}` — customer bazlı LLM token / cost tüketimi (PII-free, abuse pattern erken uyarı)
- `GET /admin/llm-usage/summary` — model × node bazlı toplam kullanım

---

## 5. Örnek Konuşmalar

Bu üç senaryo `scripts/demo_conversation.py` ile birebir çalıştırılabilir.

### A) Yeni araç valid başvuru + HGS

```
U: Yeni araç. Toyota Corolla, fatura 3 milyon, 1 milyon finansman istiyorum.
B: Taşıt finansmanı ön başvuru bilgilerinizi özetliyorum:
   - Finansman türü: Yeni taşıt
   - Araç modeli: Toyota Corolla
   - Proforma fatura değeri: 3.000.000 TL
   - Talep edilen finansman tutarı: 1.000.000 TL
   - Maksimum talep edilebilecek tutar: 1.800.000 TL
   Onaylıyor musunuz?
U: Evet onaylıyorum
B: Ön başvurunuz başarıyla oluşturuldu. Başvuru numaranız: APP-XXXXXXXXXXXX
B: Aracınızla otoyol ve köprü geçişlerinde kullanılmak üzere HGS ürünümüzü de sunabiliriz...
U: Evet
B: HGS başvurunuz alındı.
```

### B) İkinci el limit aşımı + düzeltme + başvuru

```
U: İkinci el. Kasko 4 milyon, tescil 01.06.2023, 2 milyon finansman istiyorum.
B: Talep edilebilecek maksimum finansman tutarı 1.600.000 TL olabilir.
   Talep ettiğiniz 2.000.000 TL bu limiti aşıyor.
   Bilgileri güncellemek ister misiniz?
U: Tutarı 1.5 milyon yap
B: Taşıt finansmanı ön başvuru bilgilerinizi özetliyorum:
   - Finansman türü: İkinci el taşıt
   - Araç kasko değeri: 4.000.000 TL
   - Tescil tarihi: 2023-06-01
   - Araç yaşı: 2
   - Talep edilen finansman tutarı: 1.500.000 TL
   - Maksimum talep edilebilecek tutar: 1.600.000 TL
   Onaylıyor musunuz?
U: Evet onaylıyorum
B: Ön başvurunuz başarıyla oluşturuldu...
```

### C) Mid-flow FAQ + devam + final confirmation

```
U: Yeni araç. Toyota Corolla, fatura 3 milyon, 1 milyon finansman istiyorum.
B: [özet hazır] Onaylıyor musunuz?
U: İkinci el araçta maksimum ne kadar finansman alabilirim?
B: İkinci el araçta talep edilebilecek finansman tutarı, aracın kasko değerinin
   en fazla %40'ı kadar olabilir. Ayrıca üst limit 3.000.000 TL'dir...
   Kaynak: vehicle_finance_faq.md / İkinci El Araçta Maksimum Finansman Oranı Nedir?
U: Evet onaylıyorum
B: Ön başvurunuz başarıyla oluşturuldu...
```

> Önemli: FAQ sorusu başvuru state'ini değiştirmez; kullanıcı kaldığı yerden devam eder.

---

## 5b. Why LLM Does NOT Make Financial Decisions

Bu projedeki en kritik mimari karar: **LLM finansal/regülatif kararları vermez.**

| Karar | Nerede yapılıyor | Neden LLM değil |
|-------|-----------------|------------------|
| %60 / %40 / 3M cap hesabı | `app/domain/rules.py` | Saçma sayı üretmesi (hallucination) müşteri kaybına yol açar; ayrıca denetim izinden geçmeli |
| 7M / 5M eşik kontrolü | `domain/rules.py` | Eşik değiştiğinde tek dosyada güncellenmeli; prompt'a gömülmemeli |
| Ticari / binek ayrımı | `domain/vehicle_catalog.py` | Bankanın kasko değer listesi servisi otoritedir; LLM "Ford Transit binektir" deyemez |
| TCKN checksum doğrulaması | `domain/tckn.py` | Deterministic algoritma; LLM yorumlamamalı |
| Araç yaşı hesabı | `domain/date_utils.py` | "2021 model = 5 yaş" gibi LLM hatalarını engellemek için tescil tarihinden hesaplanır |
| Kefil zorunluluğu | `domain/rules.py` | Politika; her test prod'da hukuk onayına tabi olur |
| Idempotency (duplicate başvuru) | `persistence/repositories.py` + `security/idempotency.py` | Database-level constraint; LLM bilemez |

LLM yalnızca **doğal dil → yapılandırılmış veri** (intent + alan çıkarımı) ve **bağlam → cevap** (FAQ üretimi) için kullanılır. Bu sayede:
- Bir model değişikliği (Qwen→Llama) iş kurallarını etkilemez
- Hallucination kabul edilemez bir bankacılık kararıyla sonuçlanmaz
- Tüm kararlar denetlenebilir, deterministic ve test edilebilir

Eval suite'in `validation_correctness=1.0` eşiği bu kararı zorlar.

---

## 5c. Agentic Version Design

Bu MVP **tool-constrained agent** olarak da tasarlanabilir. Şu anki LangGraph workflow'unda her node deterministic — agentik versiyonda LLM, doğru tool'u seçmekle sorumlu olur.

```text
agent loop:
  1) extract_fields_tool(user_message, state)
  2) IF finance_type known:
       validate_<new|used>_tool(fields) → ValidationResult
     ELSE: ask_finance_type_tool()
  3) IF retrievable_question(user_message):
       retrieve_faq_tool(query) → context → answer_tool(context)
  4) IF result.errors: ask_fix_field_tool(field)
     IF result.missing: ask_field_tool(field)
     IF result.valid: show_summary_tool()
  5) IF user_intent == confirm AND state == AWAITING_CONFIRMATION:
       create_application_after_confirmation_tool(state)
       create_hgs_lead_tool(state, accepted?)
```

**Tool allowlist** (`security/guardrails.py` içinde): LLM yalnızca bu yedi tool'u çağırabilir. Arbitrary SQL/HTTP/file erişimi yok. Tool inputları Pydantic schema ile validate edilir.

Bu yaklaşım case'in spirit'ini koruyup esnekliği artırır:
- Müşteri "Önce FAQ sor sonra başvuru yapalım" gibi karmaşık istekleri LLM kendisi adımlara bölebilir
- Yeni intent veya alan eklemek için graph yerine sadece tool eklenir
- Aynı deterministic validation tool'ları çağrılır → karar mekanizması değişmez

Trade-off: Agent reasoning latency artar (multiple tool calls), bu yüzden case'in MVP'sinde LangGraph state machine tercih edildi. Production yol haritasında agentic dispatch katmanı ayrı bir feature flag arkasında değerlendirilir.

---

## 5c2. LLM Gateway Architecture (LiteLLM)

Production'a daha yakın olmak için tüm LLM çağrıları artık **LiteLLM Proxy** üzerinden geçer. Uygulama kodu hiçbir model ID'sini bilmez — sadece **alias**lar (`vehicle-finance-small`, `vehicle-finance-large`, `vehicle-finance-guard`) ve **node policy**'leri kullanır.

```
LangGraph node
   │ node_purpose="faq_answer"
   ▼
LLMGatewayClient
   ├── routing_policy.get_policy()    → NodePolicy (model_alias, budgets)
   ├── budget.fit_to_budget()         → trim context / fail safe
   ├── (LiteLLM call via ChatOpenAI)
   ├── usage_logger.log_usage()       → llm_usage_logs (PII-free)
   └── on failure → fallback_alias
```

### Why LiteLLM?

| Sorun | LiteLLM çözümü |
|------|-----------------|
| Provider lock-in | Aliases üzerinden router; vLLM/Ollama/cloud aynı API ile değiştirilebilir |
| Token/cost tracking | Built-in observability + `model_info.input_cost_per_token` |
| Rate limit / TPM-RPM | LiteLLM router seviyesinde |
| Multi-model fallback | `router_settings.fallbacks` |
| Caching | Local prompt cache (FAQ tekrarı için tasarruf) |
| Multi-tenant key auth | Virtual key per uygulama (master key sadece infra) |
| Tek operasyonel kontrat | Bankanın iç AI platformuyla aynı pattern |

### Token Budgeting Strategy

Her LangGraph node'u için ayrı bütçe; magic-number değil named policy:

| Node | Model alias | Input | Output | Notlar |
|------|-------------|-------|--------|--------|
| `intent_classification` | small | 800 | 120 | Tek satır karar; küçük model yeter |
| `field_extraction` | small | 1200 | 300 | Structured JSON çıktısı |
| `faq_answer` | large | 3500 | 700 | RAG context + Türkçe akıcılık ister |
| `final_summary` | small | 1200 | 350 | Önceden hazırlanmış özet metni biçimlendir |
| `safety_check` | guard | 1000 | 100 | Llama-Guard-3-8B (hızlı, ucuz) |
| `response_generation` | small | 1500 | 400 | Genel cevap üretimi |

**Pre-call kontrol**: `fit_to_budget`
1. Estimated prompt tokens hesaplanır (tiktoken / heuristic).
2. Conversation history önce trim'lenir (en yeni mesajlar tutulur).
3. RAG chunk sayısı azaltılır.
4. Hâlâ limitin üstündeyse `BudgetExceededError` → safe deterministic reply.
5. `max_tokens` ayarı policy'den geçilir, böylece LLM cevabı budget'ı asla aşamaz.

**Post-call log** (`llm_usage_logs`): `session_id`, `customer_id_hash` (SHA-256 prefix), `conversation_step`, `node_purpose`, `model_name`, `provider`, prompt/completion/total tokens, `estimated_cost_usd`, `latency_ms`, `litellm_call_id`, `fallback_used`, `trimmed_context_count`. **Raw prompt/completion metni asla bu tabloya yazılmaz.**

### Cost vs GPU Capacity Management

- Small model 7×, large model 1× — node routing intent/extraction'ı small'a kaydırır → GPU saatinin önemli kısmı tasarruf.
- LiteLLM cache: aynı FAQ sorgusu tekrar gelirse cache'ten dönülür.
- `tpm`/`rpm` limitleri LiteLLM config'te → throttling DOWN-stream sorun yaratmadan üst katmanda kesilir.
- `trimmed_context_count > 0` rate'i izlenir → çok sık trim'lenmek RAG chunking ayarının yenilenmesi gerektiğini söyler.

### Model Routing Policy

```yaml
intent_classification → vehicle-finance-small  (fallback: large)
field_extraction      → vehicle-finance-small  (fallback: large)
faq_answer            → vehicle-finance-large
final_summary         → vehicle-finance-small  (fallback: large)
safety_check          → vehicle-finance-guard
response_generation   → vehicle-finance-small
```

Provider failure'da policy'nin `fallback_alias`'ı bir kez denenir; çift fallback yoktur.

### Local-only Production Mode

Default `ENABLE_CLOUD_FALLBACK=false`. Bu modda **hiçbir kullanıcı verisi banka dışına çıkmaz**:
- Tüm aliaslar `hosted_vllm/...` veya `ollama/...` (lokal).
- `cloud-fallback-large` alias'ı LiteLLM config'te tanımlı ama gateway client `_CLOUD_ALIASES` setini görür ve çağrıyı `CloudFallbackDisabledError` ile reddeder.
- Bu redaksiyon **uygulama kodu seviyesinde** zorlanır — LiteLLM yanlış config'le bile cloud'a çıkamaz.

### Cloud Fallback Policy

Eğer prod ekibi `ENABLE_CLOUD_FALLBACK=true` ayarlarsa:
1. PII redaction MUST run before any cloud call (TCKN, telefon, isim mask'lenir).
2. Cloud çağrısı yalnızca local hepsi fail olduğunda denenir.
3. Audit log'a `provider=cloud` event eklenir, gerçek-zamanlı alert tetiklenir.
4. Cloud quota / latency dashboard'da gösterilir.

### LiteLLM Docker Setup

```bash
# Konfigürasyon: infra/litellm/config.yaml
cp .env.example .env
# .env içinde LLM_GATEWAY_ENABLED=true olarak ayarla.

docker compose up -d litellm-db litellm
# Proxy http://localhost:4000/ adresinde çalışır.
# Admin UI: http://localhost:4000/ui  (master key ile giriş)

docker compose up -d api  # api artık LiteLLM üzerinden gider
```

Logical chain: `api` → `litellm:4000` → `vLLM 8000/8001/8002` veya `ollama:11434`.

### Admin Usage Endpoints

```bash
# Son LLM çağrı kayıtları (PII-free)
curl http://localhost:8080/admin/llm-usage

# Model x node bazlı toplam (cost dashboard için)
curl http://localhost:8080/admin/llm-usage/summary

# Mevcut node policy'leri ve gateway durumu
curl http://localhost:8080/admin/llm-budget/status
```

---

## 5d. Inference Cost Optimization

Banka chatbot'unda **inference maliyeti = (GPU saat × concurrent kullanıcı) / başarılı başvuru**. Optimizasyon stratejisi:

1. **Routing**: intent + alan çıkarımı + collection prompt + validation yumuşatma → small model (7B/14B); FAQ + uzun cevap → large (70B AWQ); safety check → guard (8B).
2. **FAQ cache.** Sık sorulan 30–50 soruyu (embedding, top-3) hash'leyip cevabını cache'le. Sözleşmesel SLA ile zaman bazlı invalidate.
3. **Embedding offline.** Doküman embedding'i bir kere üretilir; queries hash veya küçük encoder ile yapılır.
4. **Quantization.** AWQ 4-bit ile 70B → ~42 GB; throughput +%30–50.
5. **vLLM continuous batching.** Aynı GPU üzerinde 30–60 concurrent stream taşır.
6. **Short prompts.** System prompt'lar 200-300 token; context yalnızca o turn için gereken alanları içerir.
7. **Conversation summarization.** Uzun konuşmalarda raw history yerine özet besle (state'in `history` alanını trim'le).
8. **Token budget enforcement.** Her node için `max_input_tokens` / `max_output_tokens` hard cap; aşılırsa pre-call hard stop + safe deterministic reply.
9. **Customer-bazlı sliding-window kontrolü.** Saatlik + günlük token kotası — masraf güvenliği + chatbot'u kapsam dışı (örn. kod yazdırma) kullanmaya çalışan abuse pattern'ler için ikinci kontrol katmanı.
10. **Failover.** vLLM down → LiteLLM `fallback_alias` zinciri; her ikisi de down → safe deterministic reply (`response_gen` fallback metni) — kullanıcıya selamsız boş ekran asla.

---

## 6. Güvenlik Kararları

| Konu | Karar |
|------|-------|
| PII | TCKN/telefon/email loglarda maskelenir (`security/pii.py`). |
| KVKK | Açık rıza login adımında alındığı varsayılır; chatbot kişisel veriyi on-prem inference ile işler, banka dışına çıkarmaz. |
| TCKN | Checksum doğrulaması (`domain/tckn.py`); geçersizde tekrar sor. |
| Prompt injection | Pattern tabanlı blok (`security/guardrails.py`); RAG context'i de filtrelenir. |
| Tool allowlist | LLM yalnızca `ALLOWED_TOOLS` listesindeki işlevleri çağırabilir. |
| Encryption | Interface (`SecretStore`) hazır. MVP'de mask-only; prod'da KMS/HSM. |
| Idempotency | `SCOPE_APPLICATION_CREATE` + key; duplicate önlenir. |
| Audit | Tüm kritik olaylar `audit.log` + DB `audit_logs` tablosuna yazılır. |

Detaylı not: [docs/security.md](docs/security.md).

---

## 7. Test ve Eval

```bash
# Unit + flow testleri
pytest

# Eval suite (20 konuşma + 6 adversarial)
python -m app.evals.run_evals

# Demo script (5 canonik senaryo)
python -m scripts.demo_conversation
python -m scripts.demo_conversation --scenario new_vehicle_happy_path
```

Hedeflenen metrikler ve eşikler [docs/evaluation.md](docs/evaluation.md).

Demo script senaryoları:
- `new_vehicle_happy_path` — Yeni araç valid başvuru + HGS
- `used_vehicle_limit_fix` — İkinci el limit aşımı + düzeltme + başvuru
- `faq_mid_flow` — Mid-flow FAQ + devam + final confirmation
- `prompt_injection_blocked` — İki ayrı injection denemesi bloklanır, state korunur
- `duplicate_confirmation_idempotency` — İki kere onay tek başvuru üretir

---

## 8. Case Sunumunda Vurgulanacak 10 Teknik Karar

1. **LLM karar vermez** — limitler, kefil zorunluluğu, idempotency, KVKK gating tamamen kod tarafında.
2. **LangGraph state machine** — her turn baştan compile edilmiş graph üzerinden tek path; node'lar küçük, test edilebilir.
3. **LLM-first konuşma + deterministic kurallar** — niyet/alan çıkarımı, validation yumuşatma ve FAQ üretimi LLM; greeting customer-master'dan gelen ad+gender ile **template** (LLM çağrısı yok); limit/oran/kefil/idempotency/DB tamamen `rules.py` ve `security/*`'ta deterministic. Test/demo için stub extractor (`dev_extractor.py`) gerçek LLM olmadan akışı tam olarak yürütür.
4. **Deterministic rule engine** — `domain/rules.py` ile NEW/USED validatorları; eşikler magic-number değil named constant.
5. **Idempotency garantili DB write** — `(scope, key)` unique constraint; default key `session_id:confirm` + opsiyonel client `idempotency_key`.
6. **PII masking ve audit trail** — TCKN/telefon/email loglarda maskelenir; her kritik olay `audit_logs` tablosuna.
7. **Guardrail iki katmanda** — kullanıcı inputu + RAG context (dokümandan gelen "ignore instructions" satırları temizlenir); tool allowlist enforced.
8. **Vehicle catalog ayrı servis abstraksiyonu** — binek/ticari kararı LLM'e değil, katalog servisine sorulur; MVP'de mock, prod'da kasko değer servisi.
9. **LiteLLM gateway** — node bazlı routing, token budget, fallback, virtual-key auth; uygulama kodu model ID bilmez.
10. **Inline-editable summary + customer token budget** — onay öncesi UI tablo render eder, kullanıcı text-box'tan değer düzeltir; backend `edited_fields`'i merge edip kuralları yeniden koşar. Customer-bazlı sliding-window token kontrolü hem masraf hem abuse pattern erken uyarısı sağlar.

---

## 9. Üretime Geçerken Yapılacaklar

- [ ] `SecretStore` arkasına gerçek KMS/HSM (Vault, AWS KMS) bağla; TCKN'leri encrypted sakla.
- [ ] Bankanın gerçek **araç katalog / kasko değer servisi**ne entegre ol; mock `vehicle_catalog.py`'yi devre dışı bırak.
- [ ] `auth/session_context.py` mock yerine BFF JWT/oturum doğrulamasına bağla.
- [ ] Customer master servisi entegrasyonu (KKB, Findeks, mevcut limit yükü) → ön uygunluk skoru.
- [ ] Vector store'u Qdrant-cloud / Qdrant-cluster'a geçir, embedding'i `sentence-transformers` veya bank-internal multilingual modele bağla.
- [ ] LangGraph checkpointer'ı PostgreSQL'e bağla; conversation history tablo bazlı tut.
- [ ] Llama Guard / NeMo Guardrails entegrasyonu (input + output filter).
- [ ] Observability: Langfuse veya LangSmith tracing, OpenTelemetry metrics, Prometheus dashboard.
- [ ] LLM rate-limit, concurrency control ve fallback model zinciri.
- [ ] Eval suite'i CI'a bağla, eşik altına düşerse deploy'u engelle.
- [ ] Data retention politikası (audit_logs, conversation_states) ve PII silme akışı.
