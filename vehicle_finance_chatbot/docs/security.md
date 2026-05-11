# Security Notes

## Tehdit Modeli (özet)

| Tehdit | Karşılık |
|--------|----------|
| Prompt injection (kullanıcı mesajı) | `security/guardrails.py` pattern listesi + safe-reply fallback |
| Prompt injection (RAG doküman) | `check_retrieved_context` ile satır bazlı filtre |
| PII sızıntısı (log/transcript) | `security/pii.py` TCKN/telefon/email maskeleme |
| Limit/policy manipülasyonu | Limit hesaplamaları LLM dışı; `domain/rules.py` deterministic |
| Tool zincirinin sömürülmesi | `ALLOWED_TOOLS` allowlist; tool I/O Pydantic schema ile validate |
| Yetkilendirme bypass | `require_customer` zorunlu; session-customer eşleşmesi her turn'de doğrulanır |
| Duplicate başvuru | `IdempotencyRecord` unique constraint + scope/key |
| Veri at-rest | TCKN'ler stored masked; `SecretStore` interface prod'da KMS/HSM |
| KVKK | İlk turn aydınlatma + açık rıza; rıza alınmadan PII yazımı yok |

## Layer Detayları

### Input Guardrail
- Pattern-tabanlı, İngilizce + Türkçe varyantlar (`ignore previous
  instructions`, `önceki talimatları unut`, vb.)
- Bloklandığında: `state.guardrail_triggered = True`, `ActionType.SAFE_REPLY`
- Application state'i bozulmaz.

### Context Guardrail
- RAG dokümanlarından gelen satırlar pattern filtresinden geçer.
- Çünkü hostile dokümanlar veya FAQ enjekte edilmiş içerik LLM'i
  manipüle edebilir.

### Output Guardrail (gelecek iş)
- LLM cevabı içindeki finansal limit/oranlar `domain/rules` ile çapraz
  doğrulanmalı (örn. cevap "%70" derken kural %60 ise reddedilmeli).
- Llama Guard / NeMo Guardrails ile çıktı moderation.

### Tool Allowlist

Şu anda izinli:
```
extract_fields
validate_new_application
validate_used_application
retrieve_faq
create_application_after_confirmation
create_hgs_lead
handoff_to_human
```

LLM tool çağırırken `is_tool_allowed(name)` kontrolü yapılır. SQL,
shell veya arbitrary read API'ye doğrudan erişim yoktur.

### Audit

`security/audit.py` aşağıdaki kritik olayları yazar:
- `consent_accepted` / `consent_rejected`
- `field_updated`
- `validation_passed` / `validation_failed`
- `summary_shown`
- `application_persisted` (`created` + `duplicate_prevented`)
- `hgs_offered` / `hgs_accepted` / `hgs_rejected`
- `guardrail_triggered`
- `handoff`

Payload'larda PII maskelenir (`pii.mask_payload`).

### Encryption Roadmap

MVP `MaskOnlySecretStore` kullanır — kayıtlı TCKN'ler maskelidir.
Prod'da:

```python
class KmsSecretStore:
    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...
```

Banka KMS/HSM'i arkasında. Anahtar rotasyonu ve role-based decrypt
yetkisi ayrı politika.
