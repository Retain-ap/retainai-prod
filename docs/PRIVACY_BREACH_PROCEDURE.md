# Privacy breach procedure and breach record (RetainAI)

Internal procedure. The owner is RetainAI's Privacy Officer (see the Privacy Policy, section 13).
It follows PIPEDA's breach rules and Quebec's Law 25. It is not legal advice; for a serious breach,
get a lawyer's help early.

## When something may have gone wrong

1. **Contain it, today.** Revoke exposed keys, rotate passwords and tokens, close the access path,
   pause the affected feature, and preserve logs. Don't delete evidence.
2. **Work out what happened.** Which records, whose (RetainAI account holders, or a business's
   clients), how many people, how sensitive, who could see it, and since when.
3. **Decide if there is a "real risk of significant harm"** (PIPEDA) or a "risk of serious injury"
   (Quebec). Consider:
   - how sensitive the information is (financial, health, identity documents, passwords, private
     messages, contact lists);
   - how likely it is to be misused (stolen versus sent to a known person who deleted it; encrypted
     or not; how long it was exposed).
4. **If yes, notify as soon as feasible:**
   - **The Office of the Privacy Commissioner of Canada**, using its online breach report form at
     priv.gc.ca.
   - **Quebec's Commission d'accès à l'information**, if any affected person is in Quebec, using
     its form at cai.gouv.qc.ca.
   - **Affected people**, directly (usually by email), in plain language. Say:
     - what happened, when, and what information was involved;
     - what RetainAI has done;
     - what they can do to protect themselves;
     - who to contact.
   - **Affected businesses**, without undue delay, when the breach involves information about their
     clients (RetainAI's Terms promise this). Help them meet their own notification duties.
   - **Other organizations** that can reduce the harm, such as a bank or a provider.
5. **Record it** in the table below. This applies to every breach, even ones that don't need
   notice. Keep each record for at least 24 months.
6. **Fix the cause** and note the fix in the record.

## Breach record

Keep one row per incident. Personal details of affected people do not belong here; reference
them by count and type.

| # | Date found | Date it happened (or range) | What happened | Information involved | People affected (count, type) | Real risk of significant harm? Why | Notified (OPC / CAI / people / businesses), with dates | Steps taken | Recorded by |
|---|---|---|---|---|---|---|---|---|---|
| — | No breaches recorded. | | | | | | | | |

## Related

- Hosting and data locations: Render (Oregon, United States). Providers are listed in the Privacy
  Policy, section 4.
- Secrets and key rotation: Render environment variables for the `retainai-app` service.
