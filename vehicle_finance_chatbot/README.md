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
guardrail   intent /        consent      RAG /           idempotent
filter      structured      flow         FAQ retriever   DB write
            extractor                                    (SQLAlchemy)
                |
                v
    deterministic rules engine
    (NEW / USED validators)
                |
                v
        audit + PII masking
```

Detaylı diagram için [docs/architecture.md](docs/architecture.md).

### Yapı Taşı Kararları (özet)

- **LLM karar vermez.** Limit, kefil zorunluluğu, yaş üst sınırı,
  ticari/binek kontrolü, idempotency, DB yazımı tamamen
  `app/domain/rules.py` ve `app/security/*` içinde deterministic kod
  olarak çalışır. LLM yalnızca niyet anlama, doğal dilden alan çıkarma
  ve FAQ cevabı üretme için kullanılır.
- **Mock-first LLM.** `LLM_PROVIDER=mock` modunda sistem tamamen
  bağımsız `RuleBasedExtractor` + `HashEmbedder` ile çalışır. Bu sayede
  testler ve evaller harici bağımlılık olmadan koşar. Prod için vLLM
  veya Ollama OpenAI-compatible endpoint'e geçilir.
- **Auth context dışarıdan.** `X-Customer-Id` header'ı BFF'den gelir;
  müşteri profili mock store'da. Production'da bu auth katmanı bankanın
  customer-master servisine bağlanır.
- **KVKK consent ilk adımdır.** Onay alınmadan kefil/satıcı TCKN
  toplanmaz ve DB'ye başvuru yazılmaz.
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
# .env içinden LLM_PROVIDER=mock bırakırsanız LLM'siz çalışır.
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

### Mock (test/CI)

`LLM_PROVIDER=mock`. Sistem regex/heuristic tabanlı extractor
kullanır. Tüm testler ve evaller bu modda 100% geçer.

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
# Turn 1 — KVKK consent'i tetikle
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Id: CUST001" \
  -d '{"session_id":"s1","message":"merhaba"}'

# Turn 2 — onay ver
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Id: CUST001" \
  -d '{"session_id":"s1","message":"Evet, kabul ediyorum"}'

# Turn 3 — başvuru
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Id: CUST001" \
  -d '{
    "session_id":"s1",
    "message":"Yeni araç için başvuru yapacağım. Toyota Corolla, fatura 4 milyon, 2 milyon finansman istiyorum.",
    "idempotency_key":"msg-3"
  }'

# Turn 4 — özet üzerine onay
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Id: CUST001" \
  -d '{"session_id":"s1","message":"Evet onaylıyorum","idempotency_key":"confirm-1"}'

# Başvuruya bak
curl -H "X-Customer-Id: CUST001" \
  http://localhost:8080/applications/APP-XXXXXXXXXXXX
```

### Diğer endpointler

- `GET /health`
- `GET /sessions/{session_id}` — persisted conversation state
- `POST /rag/ingest` — opsiyonel; FAQ dokümanını yeniden yükler

---

## 5. Örnek Konuşmalar

Bu üç senaryo `scripts/demo_conversation.py` ile birebir çalıştırılabilir.

### A) Yeni araç valid başvuru + HGS

```
U: merhaba
B: Taşıt finansmanı ön başvuru sürecinde araç bilgileri ve gerekirse kefil/satıcı
   TCKN bilgisi gibi kişisel veriler işlenecektir... Onaylıyor musunuz? (Evet/Hayır)
U: Evet kabul ediyorum
B: Taşıt finansmanı ön başvurusu için size yardımcı olabilirim. Yeni araç mı yoksa
   ikinci el araç için mi başvuru yapmak istiyorsunuz?
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
| Self-as-guarantor kontrolü | `chatbot/nodes/field_extraction_node.py` | Compliance — müşterinin kendi TCKN'sini kefil yazamaması bankanın iç kuralı |

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

## 5d. Inference Cost Optimization

Banka chatbot'unda **inference maliyeti = (GPU saat × concurrent kullanıcı) / başarılı başvuru**. Optimizasyon stratejisi:

1. **Her mesajda LLM çağırma.** Affirmation/rejection ("evet", "hayır", "onaylıyorum") `RuleBasedExtractor`'un shortcut'larında yakalanır → LLM çağrısı yok.
2. **Routing**: 
   - Intent classifier küçük model (7B/14B) ile,
   - FAQ üretimi orta model ile (32B),
   - Yalnızca handoff edge-case'lerde 70B çalıştırılır.
3. **FAQ cache.** Sık sorulan 30–50 soruyu (embedding, top-3) hash'leyip cevabını cache'le. Sözleşmesel SLA ile zaman bazlı invalidate.
4. **Embedding offline.** Doküman embedding'i bir kere üretilir; queries hash veya küçük encoder ile yapılır.
5. **Quantization.** AWQ 4-bit ile 70B → ~42 GB; throughput +%30–50.
6. **vLLM continuous batching.** Aynı GPU üzerinde 30–60 concurrent stream taşır.
7. **Short prompts.** System prompt 250 token altında; context yalnızca o turn için gereken alanları içerir.
8. **Conversation summarization.** Uzun konuşmalarda raw history yerine özet besle (state'in `history` alanını trim'le).
9. **Deterministic shortcut'lar metrik olarak izlenir** — "LLM bypass rate" Langfuse'de dashboard'da görünür. Hedef: %60+ turn'lerde LLM hiç çağrılmasın.
10. **Failover ucuza.** vLLM down ise Ollama 14B fallback; her ikisi de down ise `LLM_PROVIDER=mock` rule-based extractor devreye girer (sistem çalışmaya devam eder).

---

## 6. Güvenlik Kararları

| Konu | Karar |
|------|-------|
| PII | TCKN/telefon/email loglarda maskelenir (`security/pii.py`). |
| KVKK | İlk adımda aydınlatma + açık rıza; rıza yoksa başvuru kapatılamaz. |
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
3. **Mock-first LLM mimarisi** — `RuleBasedExtractor` + `HashEmbedder` sayesinde testler ve evaller harici servis olmadan koşar; vLLM/Ollama pluggable.
4. **Deterministic rule engine** — `domain/rules.py` ile NEW/USED validatorları; eşikler magic-number değil named constant.
5. **Idempotency garantili DB write** — `(scope, key)` unique constraint; default key `session_id:confirm` + opsiyonel client `idempotency_key`.
6. **KVKK consent gate** — onay öncesi kefil/satıcı TCKN toplanmaz; ilk mesajdaki başvuru bilgisi consent sonrası replay edilir.
7. **PII masking ve audit trail** — TCKN/telefon/email loglarda maskelenir; her kritik olay `audit_logs` tablosuna.
8. **Guardrail iki katmanda** — kullanıcı inputu + RAG context (dokümandan gelen "ignore instructions" satırları temizlenir); tool allowlist enforced.
9. **Vehicle catalog ayrı servis abstraksiyonu** — binek/ticari kararı LLM'e değil, katalog servisine sorulur; MVP'de mock, prod'da kasko değer servisi.
10. **Resume + finance-type switch + self-as-guarantor kontrolü** — gerçek bankacılık UX edge-case'leri sade kodla çözüldü; her biri regresyon testiyle korunuyor.

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
- [ ] KVKK kapsamında aydınlatma metninin hukuk onaylı versiyonunu bağla; data retention policy uygula.
