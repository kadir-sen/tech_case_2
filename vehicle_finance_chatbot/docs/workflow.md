# Conversation Workflow

## State Machine

`ConversationStep` enum, sohbetin hangi aşamada olduğunu tutar:

```
START
  -> AWAITING_CONSENT
       -> SAFE_EXIT (rıza yok)
       -> AWAITING_INTENT (rıza alındı)
  -> AWAITING_FINANCE_TYPE
  -> COLLECTING_FIELDS
  -> VALIDATING
  -> AWAITING_FIELD_FIX
  -> AWAITING_CONFIRMATION
  -> PERSISTED
  -> AWAITING_HGS_DECISION
  -> COMPLETED
  -> HANDOFF (insan transferi)
```

## Tipik Yollar

### Yeni araç happy path

| Step | User input | Step changes to |
|------|-----------|-----------------|
| START | "merhaba" | AWAITING_CONSENT |
| AWAITING_CONSENT | "Evet" | AWAITING_INTENT |
| AWAITING_INTENT | "Yeni araç. Toyota Corolla, 4 milyon, 2 milyon istiyorum" | AWAITING_CONFIRMATION |
| AWAITING_CONFIRMATION | "Evet onaylıyorum" | PERSISTED → AWAITING_HGS_DECISION |
| AWAITING_HGS_DECISION | "Evet" | COMPLETED |

### Validation hatasından düzeltme

| Step | User input | Step changes to |
|------|-----------|-----------------|
| AWAITING_INTENT | "Yeni. Corolla, 4 milyon, 3 milyon istiyorum" | AWAITING_FIELD_FIX (60% limit aşımı) |
| AWAITING_FIELD_FIX | "Tutarı 2 milyon yap" | AWAITING_CONFIRMATION |

### FAQ mid-flow

| Step | User input | Step changes to |
|------|-----------|-----------------|
| AWAITING_CONFIRMATION | "İkinci el araçta max ne kadar?" | AWAITING_CONFIRMATION (değişmez) |

FAQ cevabı verilir; application state korunur.

## Update flow detayları

- `_detect_update_request` mesajda hangi alanı güncellemek istediğini
  anahtar kelime ile bulur (tutar, kasko, fatura, yaş, model, kefil,
  satıcı).
- Tek bir sayısal değer geçiyorsa onu o alana yazar ve diğer alan
  varsayılanlarını uygulamaz (`update_only` flag).
- Yeniden validation çalışır; ya summary'e ya da yine fix'e döner.

## Resume

`ConversationRepository.load(session_id)` ile state restore edilir.
Müşteri uygulamayı kapatıp geri geldiğinde:

- Önceki `current_step`'ten devam eder.
- Daha önce toplanmış alanlar yeniden sorulmaz.
- KVKK rızası bir kere alındığı için tekrar sorulmaz.

## HGS Cross-sell

`hgs_offer_node` ön başvuru oluşturulduktan **sonra** çalışır. Müşteri
"Evet" derse `hgs_leads` tablosuna lead yazılır; HGS satışı başvuruyu
etkilemez.

## Handoff

`handoff_node` aşağıdaki durumlarda devreye girer (MVP'de manuel
tetikleme; prod'da düşük confidence veya yüksek risk skoru):

- Müşteri kural dışı istisna talep ediyor
- Şikayet/agresif tone
- Sistem tekrarlı düşük confidence
