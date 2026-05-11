# Evaluation

Bu MVP'de eval suite **kanonik conversation senaryoları** + **adversarial
mesaj seti** üzerinde çalışır. Hedef, prod'a çıkmadan önce
deterministic regresyon yakalamak ve modeli değiştirirken kaliteyi
ölçmek.

## Çalıştırma

```bash
python -m app.evals.run_evals
```

Çıktı JSON formatında; eşik altı varsa exit code 1.

## Metrikler

| Metrik | Açıklama | Eşik |
|--------|----------|------|
| `intent_accuracy` | finance_type doğruluğu | (raporlanır) |
| `field_extraction` | requested_amount / casco_value / invoice_value / seller_tckn_skipped | (raporlanır) |
| `validation_correctness` | beklenen rejection veya max_allowed_amount doğru | 1.0 (sert) |
| `faq_retrieval` | top-3 hit içinde beklenen anahtar geçiyor | (raporlanır) |
| `end_to_end_completion` | senaryo başarısı (application yaratıldı/yaratılmadı doğru) | 0.95 |
| `guardrails` | adversarial bloklama doğruluğu | 1.0 (sert) |
| `duplicate_prevention` | iki kez onay tek başvuru üretir | 1.0 (sert) |

`validation_correctness`, `guardrails`, `duplicate_prevention` sert
eşik; biri %100'ün altına düşerse run fail eder.

## Dataset

### `conversations.jsonl`
14 senaryo:
1. Yeni araç valid
2. Yeni araç 7M üzeri rejection
3. Yeni araç 5M üzeri kefil gerekli
4. Yeni araç ticari model rejection
5. Yeni araç %60 limit aşımı
6. İkinci el valid
7. İkinci el 5 yaş üstü rejection
8. İkinci el %40 limit aşımı
9. İkinci el 3M üst barem
10. Satıcı TCKN skip
11. FAQ mid-flow
12. Final summary sonrası field update
13. İki kere onay idempotent
14. Resume after close

### `adversarial.jsonl`
6 mesaj:
- 4 prompt injection (EN + TR varyantlar)
- 2 benign kontrol

## Genişletme Önerileri

- Hallucination eval: LLM mode'da FAQ cevabı içindeki finansal sayıları
  domain/rules ile çapraz doğrula.
- Latency benchmark: turn başına p50/p95 latency, model boyutuna göre.
- Adversarial token coverage: `<|im_start|>`, gizli unicode markerleri,
  homoglyph variants.
- Concurrency stress: aynı session_id'ye paralel istek, idempotency
  altında race-condition kontrolü.
- LangSmith / Langfuse trace coverage: nodes'ın kaç turn'de devreye
  girdiğini göster.
