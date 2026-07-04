# LMS Integration API

External systems authenticate with **LMS API Key** records (Desk → LMS API Key).

## Headers

| Header | Description |
|--------|-------------|
| `X-LMS-API-Key` | Public key from LMS API Key |
| `X-LMS-API-Secret` | Secret shown once at key creation |

## Endpoints

Base URL: `{site-url}/api/method/`

### AML screening

`POST lms_saas.api.integrations.aml.screen_customer`

```json
{ "customer": "CUST-00001", "force": 0 }
```

### Credit bureau config

`POST lms_saas.api.integrations.bureau.score_applicant`

```json
{ "customer": "CUST-00001" }
```

### SMS

`POST lms_saas.api.integrations.sms.send_sms`

```json
{ "to_num": "+263771234567", "message": "Payment reminder" }
```

### Payments

`POST lms_saas.api.integrations.payments.create_intent`

```json
{ "loan": "LOAN-00001", "amount": 150.0, "provider_code": "ecocash" }
```

`POST lms_saas.api.integrations.payments.list_providers`

### Payment webhook (provider → LMS)

`POST lms_saas.api.payments.service.handle_payment_webhook?provider=ecocash`

Signed with HMAC (`lms_ecocash_webhook_secret` in site_config).

## site_config keys

See [SYSADMIN_GUIDE.md](SYSADMIN_GUIDE.md) for AML, bureau, and payment provider configuration.
