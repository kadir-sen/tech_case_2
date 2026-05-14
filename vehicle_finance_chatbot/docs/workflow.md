# Conversation Workflow

## State Machine

`ConversationStep` enum, sohbetin hangi aşamada olduğunu tutar:

```
START
  -> GREETED              (POST /chat/session — chatbot açıldığında)
  -> AWAITING_INTENT
  -> AWAITING_FINANCE_TYPE
  -> COLLECTING_FIELDS
  -> VALIDATING
  -> AWAITING_FIELD_FIX
  -> AWAITING_CONFIRMATION  (UI inline-editable summary tablo render)
  -> PERSISTED
  -> AWAITING_HGS_DECISION
  -> COMPLETED
  -> HANDOFF (insan transferi)
```

Müşteri mobil bankacılıkta zaten authenticated olduğu için ayrı bir
rıza adımı yoktur; sözleşmesel KVKK onayı login sırasında alınır.

Chatbot açılır açılmaz `POST /chat/session` çağrılır; greeting
customer-master'dan gelen `full_name` ve `gender` bilgileriyle
**deterministic template** üzerinden üretilir (LLM çağrısı yok) ve
`GREETED` step'e geçilir. Kullanıcı mesaj göndermeden önce de
selamlama görür.

## Tipik Yollar

### Yeni araç happy path

| Step | Event | Step changes to |
|------|-------|-----------------|
| START | `POST /chat/session` | GREETED (greeting üretildi) |
| GREETED | User: "Yeni araç. Toyota Corolla, 4 milyon, 2 milyon istiyorum" | AWAITING_CONFIRMATION (summary tablo render) |
| AWAITING_CONFIRMATION | UI: Onayla butonu (opsiyonel `edited_fields`) | PERSISTED → AWAITING_HGS_DECISION |
| AWAITING_HGS_DECISION | User: "Evet" | COMPLETED |

### Validation hatasından düzeltme

| Step | User input | Step changes to |
|------|-----------|-----------------|
| START | "Yeni. Corolla, 4 milyon, 3 milyon istiyorum" | AWAITING_FIELD_FIX (60% limit aşımı) |
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
