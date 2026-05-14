# Vehicle Finance Chatbot — Chat Akışı Detaylı Mimari Raporu

Refactor sonrası repo durumu: LLM-first konuşma + deterministic kurallar + rapidfuzz canonical resolve + editable summary + customer-bazlı abuse tracking. Bu rapor sistemi uçtan uca anlatır.

---

## 1. Sistem Görünümü (Top-Level)

```
┌──────────────────┐
│ Mobile Banking   │
│ App (BFF)        │
└────────┬─────────┘
         │ X-Customer-Id header
         │
   ┌─────┴──────┐
   │            │
   ▼            ▼
POST /chat/session     POST /chat
  (greeting)            (her turn)
         │
         ▼
┌──────────────────────────────────────────┐
│         FastAPI route layer              │
│  routes_chat.py                          │
│   - require_customer (auth dep)          │
│   - load conversation state              │
│   - merge edited_fields (allowlist)      │
│   - build GraphState                     │
│   - run_turn() → LangGraph               │
│   - persist state                        │
└────────────┬─────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────┐
│       LangGraph orchestrator             │
│       (chatbot/graph.py)                 │
│                                          │
│  START → load_session → guardrail        │
│         → intent → route_intent          │
│         → {faq | apply_fields | persist  │
│            | hgs_decision | cancel}      │
└────────────┬─────────────────────────────┘
             │
   ┌─────────┼──────────┬────────────┐
   ▼         ▼          ▼            ▼
LLM Layer   Deterministic Layer   RAG Layer    Persistence
- intent    - rules.py            - FAQ        - SQLAlchemy
- response  - vehicle_catalog     - Qdrant/    - idempotency
- greeting    + rapidfuzz           FAISS      - audit_logs
- FAQ ans   - tckn checksum                    - llm_usage_logs
            - money parser
             ▲
             │ tek geçit
             ▼
        ┌──────────────────────────────┐
        │ LiteLLM Gateway (port 4000)  │
        │  - per-node routing policy   │
        │  - token budget enforcement  │
        │  - customer-bazlı quota      │
        │  - usage logging (PII-free)  │
        │  - cloud fallback default OFF│
        └──────────────────────────────┘
             │
             ▼
   vLLM 72B-AWQ + 14B + Llama-Guard 8B (on-prem)
```

LLM gateway tek geçit; uygulama kodu model ID görmez, yalnızca alias (`vehicle-finance-small`, `-large`, `-guard`).

---

## 2. Konuşmanın Yaşam Döngüsü (Birebir)

### Adım 0 — Chatbot açılır
İstemci `POST /chat/session` çağırır. Mesaj **yok**. Backend:

1. `require_customer` dep'i `X-Customer-Id`'yi doğrular → `CustomerProfile` döner (`full_name`, `gender` dahil)
2. Yeni `session_id` üretilir (UUID prefix), `ConversationStateModel(current_step=START)` yaratılır
3. `greeting_node(gs)` çağrılır — **LLM çağrısı yok**:
   - `_build_greeting(customer)` deterministic template ile cevabı üretir
   - `first_name = full_name.split()[0]`, `honorific = "Hanım" if gender == "FEMALE" else "Bey"`
   - Çıktı format: `"Merhaba {first_name} {honorific}, taşıt finansmanı ön başvurunuza yardımcı olacağım. Yeni bir araç mı yoksa ikinci el bir araç mı düşünüyorsunuz? Henüz karar veremediyseniz araç finansmanı hakkında dilediğinizi bana danışabilirsiniz."`
   - `customer is None` kenar durumunda "Merhaba, ..." generic versiyon döner
4. `state.current_step = GREETED`, `actions=[SHOW_GREETING]`
5. State persist edilir → cevap istemciye

**Neden LLM değil?** Ad ve gender customer-master'da zaten doğrulanmış. LLM tahminine bırakmak (a) gereksiz token tüketir, (b) yanlış hitap riski (Yağmur/Deniz gibi unisex isimlerde) doğurur, (c) latency'yi artırır. Greeting body'si **case-spesifik tek bir asistan tonudur**; varyasyon ihtiyacı yok.

**Örnek çıktılar:**
> CUST001 (Ayşe, FEMALE): "Merhaba Ayşe Hanım, taşıt finansmanı ön başvurunuza yardımcı olacağım..."
> CUST002 (Mehmet, MALE): "Merhaba Mehmet Bey, taşıt finansmanı ön başvurunuza yardımcı olacağım..."

İlgili dosyalar:
- [app/chatbot/nodes/greeting_node.py](../app/chatbot/nodes/greeting_node.py)
- [app/domain/schemas.py:CustomerProfile.gender](../app/domain/schemas.py)
- [app/api/routes_chat.py:init_session](../app/api/routes_chat.py)

### Adım 1 — Kullanıcı mesaj yazar
İstemci `POST /chat` çağırır. İçerik:
```json
{
  "session_id": "sess-abc123...",
  "message": "Yeni araç. Toyota Corolla, fatura 3 milyon, 1 milyon finansman istiyorum.",
  "idempotency_key": "msg-1",
  "edited_fields": null
}
```

Backend:
1. `require_customer` dep
2. `ConversationRepository.load(session_id)` → mevcut state JSON olarak yüklenir
3. Cross-check: `state.customer_id` ≠ header → 403
4. `edited_fields` varsa `_merge_edited_fields` allowlist ile alanlara yazılır, `last_validation = None` (revalidate flag)
5. `GraphState(user_message, state, customer, idempotency_key, edited_fields)` oluşturulur
6. `run_turn(gs)` → LangGraph workflow

### Adım 2 — LangGraph orchestration
Her turn `chatbot/graph.py` üzerinde yürür:

```
START
  ↓
n_load_session         (state.customer_id set)
  ↓
n_guardrail            (prompt injection pattern tarar; blocked → SAFE_REPLY + END)
  ↓ route_after_guardrail
n_intent               (LLMExtractor.extract → ExtractedFields)
  ↓
n_route_intent_passthrough
  ↓ route_after_intent
  ├─ FAQ_QUESTION       → faq_router_node → END
  ├─ CANCEL/REJECT      → n_cancel → COMPLETED → END
  ├─ HGS_DECISION       → hgs_decision_node → END  (yalnız AWAITING_HGS_DECISION step'te)
  ├─ CONFIRM @AWAITING  → persistence_node → hgs_offer_node → END
  └─ default            → field_extraction_node → validation_node
                          ↓ route_after_validation
                          ├─ valid       → summary_node → END
                          ├─ missing     → collection_node → END
                          └─ errors      → END (validation_node fix prompt'u üretti)
```

Tek turn = tek path; her node deterministic ya da LLM çağrı + state mutation.

### Adım 3 — Response builder + persist
`run_turn` döndükten sonra:
1. `state.history.append(user msg + bot reply)` (transcript trail)
2. `ConversationRepository.save(state)` → DB JSON güncellemesi
3. `ChatResponse(reply, state_view, actions)` istemciye döner

---

## 3. Node Bazında Detay

### 3.1 `n_guardrail` — Prompt injection katmanı
[security/guardrails.py](../app/security/guardrails.py) — pattern listesi (TR + EN). "Önceki talimatları unut", "sistem promptunu göster", "kuralları boşver" vb. yakalar.

- Block durumunda: `gs.guardrail_blocked=True`, audit `EVENT_GUARDRAIL_TRIGGERED`, reply = `safe_reply`, action = `SAFE_REPLY`, akış END'e gider.
- State **değişmez** — kullanıcı saldırı denemesi başvuruyu bozmaz.

### 3.2 `n_intent` — LLM intent + alan çıkarımı
[chatbot/chains/extraction_chain.py:LLMExtractor](../app/chatbot/chains/extraction_chain.py)

- `LLM_GATEWAY_ENABLED=true` → `LLMGatewayClient.invoke(node_purpose=NODE_FIELD)` → LiteLLM proxy → `vehicle-finance-small` (~14B)
- Sistem promptu: [SYSTEM_INTENT_EXTRACTION](../app/chatbot/prompts.py) Türkçe few-shot + Pydantic şema dokümantasyonu içerir
- User payload: `context: {current_step, finance_type}\nuser: <kullanıcı mesajı>`
- Çıktı: `ExtractedFields` Pydantic struct
  - `intent`: `greet | start_application | provide_info | update_field | confirm | reject | cancel | faq_question | hgs_decision | undecided | unknown`
  - alanlar: `finance_type`, `invoice_value`, `vehicle_model` (ham — canonical değil), `requested_amount`, `casco_value`, `registration_date`, `vehicle_age`, `model_year`, `guarantor_tckn`, `seller_tckn`, `faq_question`, `field_to_update`, `confidence`
- Hata / JSON parse fails → `ExtractedFields(intent=UNKNOWN, confidence=0)` (chat path "anlamadım" cevabı verir, crash etmez)

Test/CI'da `app/chatbot/chains/dev_extractor.py:StubExtractor` monkey-patch ile aynı interface'i deterministic karşılar (production path hiç stub görmez).

### 3.3 `route_after_intent` — Niyet bazlı dallanma
Mevcut step ile intent'e göre tek path seçer:
- `FAQ_QUESTION` her zaman FAQ'a (state korunur — başvuru ortasında soru sorabilir)
- `CANCEL` veya non-confirmation step'te `REJECT` → `cancel` node → state.current_step=COMPLETED
- `HGS_DECISION` yalnız `AWAITING_HGS_DECISION` step'te HGS branch'ine; başka yerlerde fall-through
- `CONFIRM` yalnız `AWAITING_CONFIRMATION` step'te → `persist` (DB write)
- Diğer → `apply_fields` → `validate` → ...

### 3.4 `field_extraction_node` — Alanları state'e yaz
[chatbot/nodes/field_extraction_node.py](../app/chatbot/nodes/field_extraction_node.py)

LLM'in çıkardığı `ExtractedFields`'i `state.fields`'e merge eder. Önemli kararlar:

- **Numeric alanlar:** `>0` ise yaz, eski değerden farklıysa updated listesine ekle
- **`vehicle_model`:** **Burası kritik** — LLM ham string verir ("Tyota Korola"); `resolve_vehicle_model(raw)` rapidfuzz ile katalogtan canonical adı çıkarır (`Toyota Corolla`). Düşük confidence (< 80) ise:
  - `fields.vehicle_model = raw`
  - `metadata["vehicle_model_disambiguation"] = {raw, candidate, confidence}` → sonraki turn'de collection_node ya da response_gen "X demek istediniz, doğru mu?" sorabilir
- **`registration_date`:** öncelikli; varsa `compute_vehicle_age` ile yaş hesaplanır
- **`vehicle_age` / `model_year`:** sadece `registration_date` yoksa kabul edilir
- **TCKN validation:** `is_valid_tckn(checksum)` geçemezse `metadata["invalid_guarantor_tckn"]` (veya seller); collection_node bu metadata'ya göre yeniden sorar
- Updated alanlar varsa `EVENT_FIELD_UPDATED` audit

### 3.5 `validation_node` — Deterministic kural motoru
[chatbot/nodes/validation_node.py](../app/chatbot/nodes/validation_node.py)

`fields.finance_type`'a göre [domain/rules.py](../app/domain/rules.py)'dan biri çağrılır:

**`validate_new_vehicle_application`** kontrolleri:
- `invoice_value > 7_000_000` → error: "Araç proforma fatura değeri 7.000.000 TL üzerinde olduğu için..."
- `is_commercial_model(vehicle_model)` → error: "Ticari araç modelleri için..."
- `requested_amount > invoice_value × 0.60` → error: "Talep edilebilecek maksimum finansman tutarı X TL..."
- `invoice_value ≥ 5_000_000` → `requires_guarantor=True`, missing'e `guarantor_tckn` ekle (yoksa) veya error: "Kefil TCKN bilgisi geçersiz" (varsa ama invalid)

**`validate_used_vehicle_application`** kontrolleri:
- `registration_date` veya `vehicle_age` veya `model_year` yoksa → missing `registration_date`
- `age > 5` → error: "5 yaş üstü araçlar için..."
- `requested_amount > min(casco_value × 0.40, 3_000_000)` → error
- `seller_tckn` varsa ama checksum invalid → error

Çıktı: `ValidationResult(is_valid, errors, missing_fields, max_allowed_amount, requires_guarantor)`. **LLM bu sayıları üretmez** — `rules.py` deterministic.

`validation_node` davranışı:
- `is_valid=True` → audit `EVENT_VALIDATION_PASSED`, akış summary'e
- `errors` varsa → audit `EVENT_VALIDATION_FAILED`, `state.current_step=AWAITING_FIELD_FIX`, **`response_gen.render_validation_response(result, fields)` çağrılır** → LLM bu structured çıktıyı doğal Türkçe asistan diline çevirir:
  > "Toyota Corolla için maksimum 1.800.000 TL finansman verilebiliyor (%60 oranı nedeniyle). Talebinizi bu doğrultuda güncellemek ister misiniz?"
  - LLM ulaşılamazsa deterministic fallback: error mesajları + max_allowed kombine edilir
- `missing_fields` → `state.current_step=COLLECTING_FIELDS`, akış collect node'a

### 3.6 `collection_node` — Tek bir eksik alanı sor
[chatbot/nodes/collection_node.py](../app/chatbot/nodes/collection_node.py)

Sıralı kontrol:
1. `finance_type` yoksa → "Yeni mi ikinci el mi?" + `ASK_FINANCE_TYPE` action (LLM çağrısı yok — kısa şablon)
2. `metadata["invalid_guarantor_tckn"]` → "TCKN geçersiz, kontrol edip tekrar yazar mısınız?"
3. `metadata["invalid_seller_tckn"]` → benzer
4. `metadata["missing_fields"]` listesinden ilkini `response_gen.render_collection_prompt(missing_field, fields, requires_guarantor)` ile LLM'e ürettirir:
   > "6 milyon fatura değerli aracınız için kefil bilgisine ihtiyacımız var. Kefil olarak ekleyeceğiniz kişinin 11 haneli TCKN bilgisini paylaşır mısınız?"
   - LLM ulaşılamazsa `_FALLBACK_PROMPTS` sözlüğünden statik metin
5. Action: `ASK_FIELD` + field key

### 3.7 `summary_node` — Onay öncesi inline-editable tablo
[chatbot/nodes/summary_node.py](../app/chatbot/nodes/summary_node.py)

`_build_summary_rows(gs)` her finance_type için yapılı satır listesi üretir:

```json
{
  "type": "SHOW_SUMMARY",
  "payload": {
    "fields": [
      {"key": "finance_type", "label": "Finansman türü", "value": "Yeni taşıt", "editable": false, "type": "text"},
      {"key": "vehicle_model", "label": "Araç modeli", "value": "Toyota Corolla", "editable": true, "type": "text"},
      {"key": "invoice_value", "label": "Proforma fatura değeri", "value": 3000000, "editable": true, "type": "currency", "currency": "TRY"},
      {"key": "requested_amount", "label": "Talep edilen finansman", "value": 1000000, "editable": true, "type": "currency", "currency": "TRY"},
      {"key": "max_allowed_amount", "label": "Maksimum izinli tutar", "value": 1800000, "editable": false, "type": "currency", "currency": "TRY", "hint": "Sistemce hesaplanmıştır"}
    ],
    "primary_action": {"label": "Onayla", "intent": "confirm"},
    "secondary_actions": [{"label": "İptal", "intent": "cancel"}]
  }
}
```

**Mobile UI**: bu payload'u tablo şeklinde render eder. Her `editable: true` satırın yanında text-box; kullanıcı içeriği değiştirebilir. "Onayla" butonu istemci tarafında:
- Değişiklik yoksa → `POST /chat {message: "confirm"}`
- Değişiklik varsa → `POST /chat {message: "confirm", edited_fields: {"requested_amount": 1_700_000}}`

`max_allowed_amount` `editable: false` çünkü sistemce hesaplanır; manipüle edilmemeli.

Düz metin özet (UI render edemeyenler için) `_build_summary_text(rows)` ile üretilir ve `gs.reply()`'a eklenir. `state.current_step = AWAITING_CONFIRMATION`, audit `EVENT_SUMMARY_SHOWN`.

### 3.8 Kullanıcı onayla → `persistence_node`
[chatbot/nodes/persistence_node.py](../app/chatbot/nodes/persistence_node.py)

Pre-conditions:
- `customer is not None` ve `state.customer_id` doğru
- `finance_type` ve `last_validation.is_valid` true

`idem_key = build_application_key(session_id, idempotency_key or None)` → default `session_id:confirm`.

`ApplicationRepository.create(..., idempotency_scope=SCOPE_APPLICATION_CREATE, idempotency_key=idem_key)`:
- `IdempotencyRecord` tablosunda `(scope, key)` unique constraint
- Aynı key tekrar gelirse mevcut application döner, `created=False`
- Yeni satır → `application_id = APP-<12hex>`, masked TCKN'ler, max_allowed_amount snapshot

`state.application_id = row.application_id`, `state.current_step = PERSISTED`, audit `EVENT_APPLICATION_PERSISTED` (created flag + duplicate_prevented).

Reply: `"Ön başvurunuz başarıyla oluşturuldu. Başvuru numaranız: APP-XXXX"` (veya duplicate ise mevcut id).

### 3.9 `hgs_offer_node` — Cross-sell
[chatbot/nodes/hgs_node.py](../app/chatbot/nodes/hgs_node.py)

`persist` sonrası otomatik tetiklenir (`route_after_persist`). HGS pitch metni hard-coded tek cümledir (LLM çağrısı yok — tek-cümlelik cross-sell için değer üretmez), action `OFFER_HGS`, `state.current_step = AWAITING_HGS_DECISION`.

### 3.10 `hgs_decision_node` — Cross-sell yanıtı
Bir sonraki turn'de `AWAITING_HGS_DECISION` step'te. LLM intent → `HGS_DECISION` + `field_to_update=hgs_accepted_yes` veya `_no`. Backend `HgsRepository.create_lead` ile `hgs_leads` tablosuna yazar. `state.current_step = COMPLETED`.

### 3.11 `faq_router_node` — RAG yolu
Kullanıcı **herhangi bir step'te** soru sorduğunda (intent=`FAQ_QUESTION`):

1. Application state **değiştirilmez** — kullanıcı kaldığı yerden devam edebilir
2. `FaqRetriever.search(question, k=3)` → FAISS (mock) veya Qdrant (prod) cosine search → top chunks
3. `context_guardrail.strip_injection_lines(chunks)` — RAG dokümanından gelebilecek "ignore instructions" satırları temizlenir
4. LLM çağrısı: `SYSTEM_FAQ_ANSWER` + retrieved context (`node_purpose=NODE_FAQ`, large alias = 72B); RAG-grounded Türkçe cevap
5. LLM cevabında talimat ihlali yoksa `gs.reply` ve action `FAQ_ANSWER`
6. Akış END'e gider; bir sonraki turn'de kullanıcı kaldığı yerden devam eder

---

## 4. Deterministic Katmanlar (LLM dışı)

### 4.1 `domain/rules.py`
İş kurallarının tek otoritesi. LLM bu sayıları **asla** üretmez:
- `NEW_VEHICLE_MAX_INVOICE_VALUE = 7_000_000`
- `NEW_VEHICLE_GUARANTOR_THRESHOLD = 5_000_000`
- `NEW_VEHICLE_MAX_FINANCING_RATIO = 0.60`
- `USED_VEHICLE_MAX_AGE = 5`
- `USED_VEHICLE_MAX_FINANCING_RATIO = 0.40`
- `USED_VEHICLE_MAX_FINANCING_AMOUNT = 3_000_000`

Eşik değişirse tek dosyada güncellenir; prompt'a gömülü değil.

### 4.2 `domain/vehicle_catalog.py` + rapidfuzz
- `_CATALOG`: kayıtlı 17 model, `VehicleClass.PASSENGER`/`COMMERCIAL`
- `resolve_vehicle_model(raw)`:
  1. Önce exact / substring match (`lookup_vehicle_model`)
  2. Yoksa `rapidfuzz.process.extractOne` ile WRatio scorer → en yakın aday + skor
  3. `score ≥ 80` → `is_confident=True` (canonical olarak kabul)
  4. `60 ≤ score < 80` → aday var ama disambiguation gerekir
  5. `< 60` → eşleşme yok
- `is_commercial_model(raw)` → resolve yapar, confident commercial varsa True

**Sonuç:** kullanıcı "Tyota Korola" yazsa bile "Toyota Corolla" canonical adı state'e yazılır; "fort transit" hâlâ ticari reddi tetikler.

### 4.3 `domain/tckn.py`, `domain/date_utils.py`, `domain/money.py`
- TCKN checksum (Türkiye 11-hane algorithm)
- `compute_vehicle_age(registration_date)` — yıl-ay-gün karşılaştırma
- `parse_amount("3,5 milyon TL")` → 3_500_000 (test fixture'lar için)

### 4.4 `security/idempotency.py`
- Scope: `SCOPE_APPLICATION_CREATE`
- Key: client `idempotency_key` veya default `session_id:confirm`
- DB unique constraint `(scope, key)` üzerinde; race condition'da `IntegrityError → lookup → return existing`

### 4.5 `security/pii.py`
- TCKN/telefon/email regex → audit log payload'ında masked
- `mask_tckn(raw)` → `600*****492` (ilk 3 + son 3)

### 4.6 `security/guardrails.py`
- Input guardrail: prompt-injection pattern listesi (TR + EN)
- Context guardrail: RAG chunks'ında injection-like satırları siler
- Tool allowlist (agentic geleceği için): `ALLOWED_TOOLS` listesi

---

## 5. LiteLLM Gateway — LLM Çağrılarının Tek Geçidi

Her LLM çağrısı [app/llm_gateway/client.py:LLMGatewayClient.invoke](../app/llm_gateway/client.py)'den geçer.

### 5.1 Routing policy
[routing_policy.py:NODE_BUDGETS](../app/llm_gateway/routing_policy.py):

| Node purpose | Model alias | Max input | Max output | Fallback |
|---|---|---|---|---|
| `intent_classification` | small (14B) | 800 | 120 | large |
| `field_extraction` | small | 1200 | 300 | large |
| `faq_answer` | large (72B AWQ) | 3500 | 700 | — |
| `final_summary` | small | 1200 | 350 | large |
| `safety_check` | guard (Llama-Guard 8B) | 1000 | 100 | — |
| `response_generation` | small | 1500 | 400 | — |

Uygulama kodu model ID görmez — sadece bu alias'lar. Model swap = `infra/litellm/config.yaml` değişikliği.

### 5.2 Pre-call kontrolleri (sıralı)
1. **`_enforce_customer_budget(customer_id)`** — sliding-window:
   - Saatlik kümülatif token (`tokens_used_for_customer(hash, 3600)`) ≥ `max_tokens_per_customer_hourly` → `CustomerBudgetExceededError(window="1h")`
   - Günlük kümülatif (24h) ≥ `max_tokens_per_customer_daily` → `CustomerBudgetExceededError(window="24h")`
   - **Amaç**: cost koruması + chatbot'u kapsam dışı (kod yazdırma, uzun yaratıcı içerik) kullanmaya çalışan abuse pattern'in **ikinci kontrol katmanı**. Misuse'ta token tüketimi hızla yükselir; ilk uyarı bu sliding-window'dan gelir.

2. **Cloud routing guard** — `policy.model_alias in _CLOUD_ALIASES` ve `enable_cloud_fallback=False` → `CloudFallbackDisabledError`. Yanlış config'le bile cloud çağrısı yapılamaz; veri banka dışına çıkmaz.

3. **`fit_to_budget(policy, system_prompt, user_message, context_chunks, history)`** — token bütçesini estimate eder; conversation history'i tail'den geriye trim'ler (1/3 headroom), RAG chunks'i policy.max_context_chunks ile sınırlar. Hâlâ aşarsa `BudgetExceededError` → caller safe deterministic reply.

### 5.3 Backend (LiteLLM) çağrısı
`_default_litellm_backend(policy, system_prompt, user_message, chunks)`:
- LangChain `ChatOpenAI(base_url=litellm_base_url, api_key=virtual_key, model=policy.model_alias, max_tokens=policy.max_output_tokens)`
- `chat.invoke([SystemMessage, HumanMessage])`
- Provider hata → `ProviderError`
- Çıktıdan `usage_metadata` çek; yoksa local `count_tokens` ile estimate

### 5.4 Fallback zinciri
`ProviderError` → `_try_fallback(policy)`:
- `policy.fallback_alias` (örn. small fail → large) ile **bir kere** dene
- Hâlâ fail → propagate `ProviderError`
- Cloud alias fallback → cloud guard kontrolü tekrar koşar

### 5.5 Post-call logging
[usage_logger.log_usage](../app/llm_gateway/usage_logger.py) → `llm_usage_logs` tablosu:
- `customer_id_hash` (SHA-256 12 char prefix — PII değil, korelasyon için)
- `session_id`, `conversation_step`, `node_purpose`
- `model_name`, `provider`, prompt/completion/total tokens
- `estimated_cost_usd` (rate table × tokens)
- `latency_ms`, `litellm_call_id`, `fallback_used`, `trimmed_context_count`
- **Raw prompt veya completion metni asla yazılmaz** — schema-level PII protection

---

## 6. Customer-Bazlı Abuse Tracking + Admin Endpoint

[GET /admin/customer-token-usage/{customer_id}](../app/api/routes_admin.py) döner:

```json
{
  "customer_id_hash": "a3f8...",
  "calls": 47,
  "total_tokens": 18230,
  "estimated_cost_usd": 0.0142,
  "tokens_last_1h": 6200,
  "tokens_last_24h": 18230,
  "recent": [
    {"created_at": "...", "node_purpose": "field_extraction", "model_name": "vehicle-finance-small", "total_tokens": 245, "fallback_used": false}
  ],
  "limits": {"hourly": 30000, "daily": 200000},
  "status": {"over_hourly": false, "over_daily": false}
}
```

Use-case: bir kullanıcı sürekli "şu Python kodunu yaz" gibi kapsam dışı istekler gönderiyorsa:
- Guardrail bazı injection deneyimlerini bloklar
- Bloklanmayan jailbreak denemeleri **yine** LLM çağrısı tüketir
- Saatlik sliding window 30K token'ı aşar → `CustomerBudgetExceededError` → chat path "Bugün için kullanım limitine ulaştınız" + audit event
- Banka analitik dashboard `over_hourly=true` müşterileri görür, incelemeye alır

---

## 7. UI Entegrasyon — Action-Driven Render

Backend `actions[]` array'iyle UI'ya nasıl render edeceğini söyler:

| ActionType | Anlamı | UI render |
|---|---|---|
| `SHOW_GREETING` | İlk açılış selamlama | Hoşgeldin kartı |
| `ASK_FINANCE_TYPE` | Yeni/ikinci el sorusu | Chip butonları (opsiyonel) |
| `ASK_FIELD` | Tek alan iste | Text input + label |
| `FIX_FIELD` | Validation hatası | Hata bandı + text input |
| `SHOW_SUMMARY` | Inline-editable tablo | Tablo + her satır editable text/currency/date; primary "Onayla" butonu |
| `CONFIRM` | Başvuru oluşturuldu | Application id kartı + "Detay" butonu |
| `OFFER_HGS` | HGS cross-sell | Evet/Hayır butonları |
| `FAQ_ANSWER` | RAG cevabı | Sade balon + "Kaynak: vehicle_finance_faq.md / X" link |
| `HANDOFF` | İnsan operatöre transfer | Transfer banner'ı |
| `SAFE_REPLY` | Guardrail bloku | "Bu talebi karşılayamıyorum" balonu |

`SHOW_SUMMARY` payload'ı yapılı tablo verisi içerir; UI text-box render eder. Düzenleme sonrası istemci `POST /chat` çağrısında `edited_fields` ile sadece **değişen alanları** gönderir.

---

## 8. Edited-Fields Akışı (Detay)

Senaryo: kullanıcı 1M finansman istemiş, özet görmüş, "aslında 1.7M" diye revize etmek istiyor.

1. **UI tarafı:** `requested_amount` text-box'unda `1000000` yazıyor. Kullanıcı `1700000` yazıyor, "Onayla" basıyor.
2. **İstemci POST /chat:**
   ```json
   {
     "session_id": "...",
     "message": "confirm",
     "edited_fields": {"requested_amount": 1700000}
   }
   ```
3. **Backend:** `_merge_edited_fields(state, payload)`:
   - Allowlist: `{invoice_value, casco_value, vehicle_model, requested_amount, registration_date, guarantor_tckn, seller_tckn}`
   - Allowlist dışındaki key'ler **silently skipped** (örn. `max_allowed_amount` istemci manipüle edemez)
   - Tip dönüşümleri Pydantic-uyumlu (`float`, `date.fromisoformat`, vb.)
   - `state.last_validation = None` (re-validate gerekiyor)
4. **Graph akışı:** intent `confirm`, ama `last_validation is None` olduğundan `route_after_intent` → `apply_fields` → `validate`. Yeni `requested_amount`'la kurallar yeniden çalışır.
5. **Sonuç:**
   - 1.7M, 3M fatura için %60 = 1.8M sınırının altında → valid → summary tekrar gösterilir (kullanıcıya "değişiklik aldı, doğru mu?" şeklinde)
   - Veya 1.7M hâlâ üst sınırı aşıyorsa → `response_gen` doğal Türkçe ile yeni max'i belirtir

**Güvenlik:** istemci asla `last_validation` veya `max_allowed_amount`'ı override edemez; her edit kuralları yeniden tetikler.

---

## 9. Hata Yönetimi / Fallback Matrisi

| Hata Noktası | Yakalama | Kullanıcı deneyimi |
|---|---|---|
| Guardrail blok | `n_guardrail` → `gs.guardrail_blocked` | "Bu talebi karşılayamıyorum" + state korunur |
| LLM provider down | `ProviderError` → `_try_fallback(fallback_alias)` | Şeffaf — small fail olursa large çalışır |
| Tüm LLM down | `BudgetExceededError` veya `ProviderError` raise | `LLMExtractor` boş `ExtractedFields(intent=UNKNOWN)` → chat "anlamadım, tekrarlar mısınız?" |
| Pydantic parse fail | LLM JSON bozuk | Aynı: boş ExtractedFields |
| TCKN invalid | `is_valid_tckn=False` | Collection node "TCKN geçersiz, tekrar yazar mısınız?" |
| Customer quota aşıldı | `CustomerBudgetExceededError` | "Bugün kullanım limitine ulaştınız" + admin alert |
| Vehicle model bilinmeyen | `resolve.is_confident=False` + low score | UI'a raw geçer; sonraki turn'de disambiguation prompt'u |
| Duplicate confirm | Idempotency lookup | Aynı `application_id` döner, `created=False` |

Chat path **hiçbir koşulda** crash etmez; en kötü durumda "anlamadım, tekrarlar mısınız?" + state korunur.

---

## 10. Persistence Şeması

| Tablo | Amaç | Anahtar alanlar |
|---|---|---|
| `customer_sessions` | Session-customer eşlemesi | session_id (PK), customer_id |
| `conversation_states` | Per-session JSON state | session_id (PK), state_json |
| `vehicle_finance_applications` | Ön başvuru | application_id (PK), customer_id, finance_type, amounts, masked TCKNs, max_allowed_amount, idempotency_key |
| `idempotency_records` | Duplicate önleme | (scope, key) UNIQUE, target_id |
| `hgs_leads` | Cross-sell sonucu | customer_id, related_application_id, interest |
| `audit_logs` | Her kritik olay | event_type, session_id, customer_id, payload (PII-masked) |
| `llm_usage_logs` | Token/cost tracking | customer_id_hash, node_purpose, tokens, latency, fallback_used |

---

## 11. Örnek Tam Senaryo Trace'i

**Senaryo:** Yeni Toyota Corolla yazım hatalı + tutar düzeltmesi + HGS reddi

### Turn 0 — `POST /chat/session`
- Backend: `greeting_node` → deterministic template (`full_name`+`gender` slot doldurma) → "Merhaba Ayşe Hanım, ..."
- State: `START → GREETED`
- Action: `SHOW_GREETING`
- **LLM çağrısı yok** — customer-master ad ve gender bilgisi yeterli

### Turn 1 — `POST /chat {"message": "Yeni Tyota Korola, fatura 3 milyon, 1 milyon finansman istiyorum.", ...}`
1. `n_guardrail` → temiz
2. `n_intent` → LLM small → `ExtractedFields(intent=start_application, finance_type=NEW, vehicle_model="Tyota Korola", invoice_value=3000000, requested_amount=1000000)`
3. `route_after_intent` → `apply_fields`
4. `field_extraction_node`:
   - `resolve_vehicle_model("Tyota Korola")` → rapidfuzz: skor 84.6 → `is_confident=True`, model = "Toyota Corolla"
   - `fields.vehicle_model = "Toyota Corolla"` (canonical)
   - `fields.finance_type=NEW`, `fields.invoice_value=3M`, `fields.requested_amount=1M`
   - Audit `EVENT_FIELD_UPDATED`
5. `validation_node`:
   - `is_commercial_model("Toyota Corolla")` → False (passenger)
   - `invoice_value 3M ≤ 7M` ✓
   - `requested 1M ≤ 3M × 0.60 = 1.8M` ✓
   - `invoice 3M < 5M guarantor threshold` → no guarantor needed
   - Result: `is_valid=True, max_allowed_amount=1.8M`
   - Audit `EVENT_VALIDATION_PASSED`
6. `summary_node`:
   - Rows: 4 alan + max_allowed_amount
   - Text: "Taşıt finansmanı ön başvuru bilgilerinizi özetliyorum: ..."
   - Action: `SHOW_SUMMARY` with payload
   - State: `AWAITING_CONFIRMATION`
   - Audit `EVENT_SUMMARY_SHOWN`

### Turn 2 — Kullanıcı tabloda `requested_amount` text-box'unu 1700000 yapıp Onayla'ya bastı
- İstemci: `POST /chat {"message": "confirm", "edited_fields": {"requested_amount": 1700000}, "idempotency_key": "confirm-1"}`
- Backend `_merge_edited_fields` → `fields.requested_amount = 1.7M`, `last_validation = None`
- Graph:
  1. `n_intent` → `intent=confirm`
  2. `route_after_intent`: `intent==confirm` ve `step==AWAITING_CONFIRMATION` → `persist`
  3. **Ama:** `persistence_node` `last_validation is None` → guard, "Önce başvuru bilgileri doğrulanmalı" — kullanıcı yeniden onaylayacak.

> **Bilinen keskin uç:** `edited_fields` merge sonrası `intent=confirm` ile gelirse persistence guard tetikler. Çözüm: `routes_chat` katmanında `edited_fields` varsa kullanıcı mesajını `"confirm"` yerine boş ya da `"update"`'e çevirip graph'ı `apply_fields → validate → summary` yoluna zorlayabiliriz. Mevcut implementasyonda kullanıcı önce edit gönderir (özet yenilenir), sonra ayrı bir turn'de onaylar. Production iyileştirmesi olarak `intent_override` veya yeni endpoint `POST /chat/confirm` eklenebilir.

### Turn 3 — Kullanıcı "Evet onaylıyorum"
- `intent=confirm`, `step=AWAITING_CONFIRMATION` → `persist`
- `ApplicationRepository.create(idempotency_key=session_id:confirm)` → yeni APP-XXXX
- State: `PERSISTED`
- `route_after_persist` → `hgs_offer`
- `hgs_offer_node`: HGS pitch reply, action `OFFER_HGS`, state `AWAITING_HGS_DECISION`

### Turn 4 — "Hayır"
- `intent=hgs_decision, field_to_update=hgs_accepted_no`
- `hgs_decision_node`: `HgsLead(interest=False)` kaydı, state `COMPLETED`
- Reply: "Tercihinizi not aldık. Taşıt finansmanı sürecinize devam edebilirsiniz."

---

## 12. Test ve Eval Topolojisi

| Test grubu | Kapsam |
|---|---|
| `test_rules_new_vehicle` (6) | rules.py NEW kuralları |
| `test_rules_used_vehicle` (6) | rules.py USED kuralları |
| `test_vehicle_catalog` (7) | rapidfuzz canonical resolve |
| `test_tckn` (3) | checksum |
| `test_money_parser` (11) | "3,5 milyon" → 3500000 |
| `test_graph_flow_new_vehicle` (5) | E2E NEW akışları |
| `test_graph_flow_used_vehicle` (5) | E2E USED akışları |
| `test_faq_inflight` (2) | FAQ state'i korur |
| `test_guardrails` (5) | injection blok |
| `test_idempotency` (3) | duplicate önleme |
| `test_rag` (3) | retriever |
| `test_llm_gateway` (16) | gateway, routing, budget, log |
| `test_regression_review` (15) | TR normalization + invalid TCKN |
| `test_greeting` (4) | greeting node task-scope + personalization |
| `test_response_gen` (5) | validation/collection LLM-yumuşatma fallback |
| `test_edited_fields` (4) | inline-editable summary E2E |
| `test_customer_budget` (2) | sliding-window enforcement |

Toplam **102 test**, 0 fail. CI'da gerçek LLM yok — `StubExtractor` aracılığıyla deterministic akış.

Eval suite (`python -m app.evals.run_evals`) 16 senaryo + 6 adversarial; tüm metrikler `rate=1.0`.

---

## 13. "LLM-First" Kararının Anlamı

**LLM'in karar verdiği şeyler:**
- Niyet sınıflandırma (greet/start_app/confirm/...)
- Doğal dilden alan çıkarımı ("3,5 milyon" → 3500000)
- Validation çıktısının kelimeleştirilmesi
- FAQ cevabı (RAG-grounded)
- Collection prompt tonu

**LLM'in karar vermediği şeyler:**
- Limit hesabı (`rules.py`)
- Oran (%60, %40, 3M cap)
- Kefil zorunluluğu (5M eşik)
- Yaş kapısı (5 yaş)
- Ticari/binek (`vehicle_catalog`)
- TCKN checksum (`tckn.py`)
- Idempotency (`idempotency.py`)
- Cost / abuse limit (`customer budget`)
- Greeting (template — `full_name` + `gender` slot)

---

## 14. Operasyonel Görünüm — Banka Açısından

- **Token cost dashboard:** `/admin/llm-usage/summary` model × node × cost
- **Müşteri abuse görünümü:** `/admin/customer-token-usage/{cid}` sliding-window
- **Audit trail:** her kritik olay `audit_logs` tablosunda PII-masked
- **Idempotency garantisi:** ağ retry'larında duplicate başvuru yok
- **On-prem inference:** `enable_cloud_fallback=False` default; cloud çağrısı kod seviyesinde bloklu
- **Test/CI bağımsızlık:** `StubExtractor` ile gerçek LLM olmadan 102 test geçer
