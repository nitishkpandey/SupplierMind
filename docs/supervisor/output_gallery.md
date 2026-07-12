# Output Gallery — Three Paradigms Side by Side

Benchmark run `1b6417b9-15a4-4422-b188-cd4bae6ed038` (GPT-4o-mini, 2026-07-10).
Five representative queries; per paradigm: returned suppliers, the
reasoning/evidence it produced, latency and cost. Built by
`backend/scripts/build_output_gallery.py`, no manual edits to outputs.

---

## Q1 (simple): “Find metal suppliers in Germany”

Ground truth: 5 matching supplier(s) in the corpus.

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 2.7s · $0.0001*

**Returned:**
- Thyssenkrupp AG *(not in corpus)*
- Salzgitter AG *(not in corpus)*
- Klockner & Co SE *(not in corpus)*
- Metallbau Schmid GmbH *(not in corpus)*
- Häfner Metall GmbH *(not in corpus)*

**Model reasoning:**

> A leading global steel and materials company based in Germany, known for its wide range of metal products.; One of the largest steel producers in Germany, offering various metal products and solutions.; A major distributor of steel and metal products in Germany, providing a wide selection of materials.; A regional supplier specializing in custom metal fabrication and supply in Germany.; A supplier of various metal products, including sheets and profiles, catering to different industries in Germany.

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.80 · MRR 1.00 · CSR 1.00 · 3.5s · $0.0003*

**Returned:**
- Duesseldorf Metals AG
- Dortmund Metals AG
- Munich Metals Ltd.
- Stuttgart Metals GmbH
- Berlin Metals Ltd.

**Model reasoning:**

> Duesseldorf Metals AG is located in Düsseldorf, Germany, and specializes in precision metal components with a high capacity of 39552.0 kg/month.; Dortmund Metals AG is based in Dortmund, Germany, and has a strong certification profile including AS9100 and IATF 16949, with a capacity of 5664.0 kg/month.; Munich Metals Ltd. is located in Munich, Germany, and specializes in precision metal components with a capacity of 2603.0 kg/month.; Stuttgart Metals GmbH is situated in Stuttgart, Germany, and has a capacity of 8741.0 kg/month, along with multiple relevant certifications.; Berlin Metals Ltd. i…

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 10.7s · $0.0011*

**Returned:**
- *(no suppliers returned)*

**Observation:** P1 produced parametric supplier names but no corpus-resolved IDs; P2 returned 5 suppliers (P@5=0.80); P3 returned no suppliers before compliance evidence, consistent with clarification or early-stop behavior.

---

## Q10 (medium): “Electronics supplier in Germany with ISO 9001 and RoHS, lead time under 30 days”

Ground truth: 1 matching supplier(s) in the corpus.

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 4.4s · $0.0002*

**Returned:**
- RS Components *(not in corpus)*
- Farnell *(not in corpus)*
- Digi-Key Electronics *(not in corpus)*
- Mouser Electronics *(not in corpus)*
- Conrad Electronic *(not in corpus)*

**Model reasoning:**

> RS Components is a well-known electronics supplier in Germany that offers a wide range of electronic components and has ISO 9001 certification. They also comply with RoHS regulations and typically have a lead time under 30 days.; Farnell is a reputable distributor of electronic components in Germany, known for their quality assurance with ISO 9001 certification. They provide RoHS compliant products and have efficient logistics to ensure lead times are generally under 30 days.; Digi-Key is a global supplier with a strong presence in Europe, including Germany. They are ISO 9001 certified and off…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.20 · MRR 1.00 · CSR 0.60 · 3.5s · $0.0003*

**Returned:**
- Bremen Electronics AG
- Stuttgart Electronics GmbH
- Duesseldorf Electronics AG
- Dortmund Electronics Ltd.
- Berlin Electronics AG

**Model reasoning:**

> Bremen Electronics AG has both ISO 9001 and RoHS certifications, making it a suitable choice for the user's requirements.; Stuttgart Electronics GmbH has ISO 9001 certification, but lacks RoHS. However, it is a strong candidate due to its capacity and location.; Duesseldorf Electronics AG has RoHS certification but lacks ISO 9001. It is included for its high capacity and relevance to the electronics market.; Dortmund Electronics Ltd. has ISO 9001 certification but lacks RoHS. It is included for its capacity and market relevance.; Berlin Electronics AG has ISO 9001 certification but lacks RoHS.…

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.20 · MRR 1.00 · CSR 0.79 · 24.4s · $0.0029*

**Returned:**
- Bremen Electronics AG
- Duesseldorf Electronics AG

**Per-constraint verdicts:**
- **Duesseldorf Electronics AG** — 3/3 constraints PASS
- **Bremen Electronics AG** — 3/3 constraints PASS
- **Stuttgart Electronics GmbH** — 2/3 constraints PASS; failed: RoHS: REACH is explicitly not equivalent to RoHS
- **f1696ae7-2954-45a3-8cf3-0ec927a3a331** — 2/3 constraints PASS; failed: RoHS: CE is explicitly not equivalent to RoHS
- **784e8080-5315-4006-a50d-879bb6afdfad** — 2/4 constraints PASS; failed: country: Supplier is in Czech Republic, required country is Germany; lead_time: Lead time 33d slightly exceeds 30d limit
- **8b444bda-1e28-4c18-bc73-87dba8ff1122** — 1/3 constraints PASS; failed: RoHS: The supplier does not hold any related certification to RoHS.; lead_time: Lead time 79d exceeds 30d limit
- **Berlin Electronics AG** — 1/3 constraints PASS; failed: RoHS: The supplier does not hold any certification equivalent or related to RoHS.; lead_time: Lead time 35d exceeds 30d limit
- **7b497246-8067-4f34-9b8e-dc5d02575bc1** — 1/3 constraints PASS; failed: RoHS: The supplier does not hold any related certification to RoHS.; lead_time: Lead time 55d exceeds 30d limit
- **Dortmund Electronics Ltd.** — 1/3 constraints PASS; failed: RoHS: The supplier does not hold any related certification to RoHS.; lead_time: Lead time 63d exceeds 30d limit
- **9ac203de-545f-4704-bf79-bee914a4740d** — 1/4 constraints PASS; failed: country: Supplier is in France, required country is Germany; RoHS: The supplier does not hold any related certification to RoHS.

**Observation:** P1 produced parametric supplier names but no corpus-resolved IDs; P2 returned 5 suppliers (P@5=0.20); P3 returned 2 evidence-gated supplier(s) (P@5=0.20, CSR=0.79).

---

## Q14 (medium): “Packaging manufacturer with 50000+ units per month capacity in Netherlands”

Ground truth: 3 matching supplier(s) in the corpus.

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 2.8s · $0.0001*

**Returned:**
- Smurfit Kappa *(not in corpus)*
- Mondi Group *(not in corpus)*
- VPK Packaging *(not in corpus)*
- DS Smith *(not in corpus)*
- Papeteries de Genval *(not in corpus)*

**Model reasoning:**

> A leading provider of paper-based packaging solutions with multiple facilities in the Netherlands, capable of high-volume production.; An international packaging and paper group with a strong presence in the Netherlands, known for its large-scale manufacturing capabilities.; A prominent packaging manufacturer in Europe, VPK has operations in the Netherlands and can handle large production volumes.; A global leader in sustainable packaging solutions with facilities in the Netherlands, capable of producing over 50,000 units monthly.; A manufacturer specializing in paper and cardboard packaging, …

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.60 · MRR 1.00 · CSR 1.00 · 3.8s · $0.0002*

**Returned:**
- Rotterdam Packaging GmbH
- Amsterdam Packaging B.V.
- Rotterdam Packaging B.V.

**Model reasoning:**

> Rotterdam Packaging GmbH has a capacity of 304,433 units/month and is located in the Netherlands, making it a strong match for the user's requirements.; Amsterdam Packaging B.V. has a capacity of 193,560 units/month and is based in the Netherlands, fulfilling the user's criteria.; Rotterdam Packaging B.V. offers a capacity of 194,037 units/month and is situated in the Netherlands, aligning well with the user's needs.

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.60 · MRR 1.00 · CSR 0.87 · 41.3s · $0.0016*

**Returned:**
- Amsterdam Packaging B.V.
- Rotterdam Packaging GmbH
- Rotterdam Packaging B.V.

**Per-constraint verdicts:**
- **Rotterdam Packaging B.V.** — 2/2 constraints PASS
- **Rotterdam Packaging GmbH** — 2/2 constraints PASS
- **Amsterdam Packaging B.V.** — 2/2 constraints PASS
- **Bremen Packaging Ltd.** — 2/3 constraints PASS; failed: country: Supplier is in Germany, required country is Netherlands
- **5d512ab6-0fe4-4173-9fc3-e78124eb07ca** — 2/3 constraints PASS; failed: country: Supplier is in Germany, required country is Netherlands
- **634d2152-4f52-4fac-a036-6aab159d1c8e** — 2/3 constraints PASS; failed: country: Supplier is in Germany, required country is Netherlands
- **7b3884c1-bda9-422d-be24-6873f0d1e69c** — 2/3 constraints PASS; failed: country: Supplier is in France, required country is Netherlands
- **Cologne Packaging GmbH** — 2/3 constraints PASS; failed: country: Supplier is in Germany, required country is Netherlands
- **Krakow Packaging S.A.** — 2/3 constraints PASS; failed: country: Supplier is in Poland, required country is Netherlands
- **Hannover Packaging AG** — 2/3 constraints PASS; failed: country: Supplier is in Germany, required country is Netherlands

**Observation:** P1 produced parametric supplier names but no corpus-resolved IDs; P2 returned 3 suppliers (P@5=0.60); P3 returned 3 evidence-gated supplier(s) (P@5=0.60, CSR=0.87).

---

## Q23 (hard): “Packaging within 40km of Berlin, ISO 9001, 100000+ units/month, under 10 days”

Ground truth: 0 matching supplier(s) in the corpus. **No supplier satisfies all constraints — correct answer is the empty set.**

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 4.0s · $0.0002*

**Returned:**
- Mondi Group *(not in corpus)*
- Smurfit Kappa *(not in corpus)*
- DS Smith *(not in corpus)*
- Schumacher Packaging *(not in corpus)*
- Packsize *(not in corpus)*

**Model reasoning:**

> Mondi is a global leader in packaging and paper, with facilities in Europe, including near Berlin. They have ISO 9001 certification and the capacity to produce large volumes quickly.; Smurfit Kappa specializes in paper-based packaging solutions and has a strong presence in Europe. They are ISO 9001 certified and can meet high-volume demands.; DS Smith is known for sustainable packaging solutions and has operations in Germany. They are ISO 9001 certified and capable of producing over 100,000 units per month.; Schumacher Packaging is a German company that offers a wide range of packaging solutio…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.00 · MRR 0.00 · CSR 0.62 · 2.9s · $0.0003*

**Returned:**
- Bremen Packaging Ltd.
- Cologne Packaging GmbH
- Hannover Packaging AG
- Krakow Packaging S.A.

**Model reasoning:**

> Bremen Packaging Ltd. is located within 40km of Berlin, has ISO 9001 certification, a capacity of 454228 units/month, and can meet the requirement of under 10 days.; Cologne Packaging GmbH is within 40km of Berlin, holds ISO 9001 certification, has a capacity of 92527 units/month, and can deliver within the required timeframe.; Hannover Packaging AG is located within 40km of Berlin, certified with ISO 9001, has a capacity of 357046 units/month, and can fulfill the order in under 10 days.; Krakow Packaging S.A. is within 40km of Berlin, has ISO 9001 certification, a capacity of 323205 units/mon…

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.46 · 45.0s · $0.0021*

**Returned:**
- *(no suppliers returned)*

**Per-constraint verdicts:**
- **Bremen Packaging Ltd.** — 2/4 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; lead_time: Lead time 58d exceeds 10d limit
- **Rotterdam Packaging GmbH** — 2/4 constraints PASS; failed: country: Supplier is in Netherlands, required country is Berlin; lead_time: Lead time 78d exceeds 10d limit
- **Hannover Packaging AG** — 2/4 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; lead_time: Lead time 61d exceeds 10d limit
- **3dbd0b9e-a251-41ea-b45c-857c7b548925** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity 69 units/month is below minimum 100,000
- **634d2152-4f52-4fac-a036-6aab159d1c8e** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001
- **7b0fb172-c804-4515-9065-44068ab5f43c** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity unit mismatch: supplier has projects/month, required units/month
- **dd59e57d-0ec7-43b3-8b36-42baa6402357** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity unit mismatch: supplier has projects/month, required units/month
- **3b50815b-9357-4950-bbb6-bbcd85aa0d9d** — 1/4 constraints PASS; failed: country: Supplier is in Poland, required country is Berlin; capacity: Capacity unit mismatch: supplier has shipments/day, required units/month
- **f3e175a3-1215-4b50-aee0-f93bbd3360d7** — 1/4 constraints PASS; failed: country: Supplier is in Czech Republic, required country is Berlin; capacity: Capacity unit mismatch: supplier has shipments/day, required units/month
- **Cologne Packaging GmbH** — 1/4 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity 92,527 is slightly below minimum 100,000 units/month

**Observation:** P1 produced parametric supplier names but no corpus-resolved IDs; P2 returned 4 suppliers (P@5=0.00); P3 gathered compliance evidence but ranked no supplier (CSR=0.46).

---

## Q19 (hard): “ISO 9001 certified bronze supplier within 50km of Bremen, 3000+ kg/month, lead time under 21 days”

Ground truth: 0 matching supplier(s) in the corpus. **No supplier satisfies all constraints — correct answer is the empty set.**

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 3.7s · $0.0002*

**Returned:**
- Bronze GmbH *(not in corpus)*
- Metallwerk Bremen *(not in corpus)*
- Bremen Bronze Solutions *(not in corpus)*
- Norddeutsche Metallwerke *(not in corpus)*
- Hannover Bronze Co. *(not in corpus)*

**Model reasoning:**

> Located within 30km of Bremen, Bronze GmbH specializes in high-quality bronze products and is ISO 9001 certified. They have the capacity to meet the monthly demand and maintain a lead time of under 21 days.; This supplier is based in Bremen and offers a range of bronze materials. They are ISO 9001 certified and can supply over 3000 kg per month with a reliable lead time.; A local supplier known for their bronze manufacturing, Bremen Bronze Solutions is ISO 9001 certified and has the capability to fulfill large orders within the specified lead time.; Located just outside Bremen, this company sp…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.00 · MRR 0.00 · CSR 0.63 · 2.9s · $0.0003*

**Returned:**
- Bremen Textiles S.A.
- Bremen Packaging Ltd.
- Bremen Electronics AG
- Dortmund Metals AG
- Duesseldorf Metals AG

**Model reasoning:**

> Bremen Textiles S.A. is ISO 9001 certified, located in Bremen, and has a capacity of 42251.0 meters/month, which exceeds the required 3000+ kg/month.; Bremen Packaging Ltd. is ISO 9001 certified, located in Bremen, and has a capacity of 454228.0 units/month, which exceeds the required 3000+ kg/month.; Bremen Electronics AG is ISO 9001 certified, located in Bremen, and has a capacity of 38353.0 units/month, which exceeds the required 3000+ kg/month.; Dortmund Metals AG is ISO 9001 certified, located within 50km of Bremen, and has a capacity of 5664.0 kg/month, meeting the requirement.; Duesseld…

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.77 · 14.6s · $0.0018*

**Returned:**
- Stuttgart Metals GmbH

**Per-constraint verdicts:**
- **Stuttgart Metals GmbH** — 3/4 constraints PASS; failed: lead_time: Lead time 23d slightly exceeds 21d limit
- **5c5c0820-ebd9-4f16-af85-279282909442** — 3/4 constraints PASS; failed: lead_time: Lead time 41d exceeds 21d limit
- **Duesseldorf Metals AG** — 3/4 constraints PASS; failed: lead_time: Lead time 66d exceeds 21d limit
- **Dortmund Metals AG** — 3/4 constraints PASS; failed: lead_time: Lead time 77d exceeds 21d limit
- **Bremen Textiles S.A.** — 3/5 constraints PASS; failed: product_fit: Supplier category 'textiles' and description do not match requested product 'bronze supplier'; capacity: Capacity unit mismatch: supplier has meters/month, required kg/month
- **62b4ccc4-e934-4f85-a7b2-22b1483d40f3** — 2/4 constraints PASS; failed: capacity: Capacity 1,878 kg/month is below minimum 3,000; lead_time: Lead time 82d exceeds 21d limit
- **Berlin Metals Ltd.** — 2/4 constraints PASS; failed: ISO 9001: ISO 27001 is explicitly not equivalent to ISO 9001; lead_time: Lead time 82d exceeds 21d limit
- **Munich Metals Ltd.** — 2/4 constraints PASS; failed: capacity: Capacity 2,603 is slightly below minimum 3,000 kg/month; lead_time: Lead time 47d exceeds 21d limit
- **Bremen Electronics AG** — 2/5 constraints PASS; failed: product_fit: Supplier category 'electronics' and description do not match requested product 'bronze supplier'; capacity: Capacity unit mismatch: supplier has units/month, required kg/month
- **Bremen Packaging Ltd.** — 2/5 constraints PASS; failed: product_fit: Supplier category 'packaging' and description do not match requested product 'bronze supplier'; capacity: Capacity unit mismatch: supplier has units/month, required kg/month

**Observation:** P1 produced parametric supplier names but no corpus-resolved IDs; P2 returned 5 suppliers (P@5=0.00); P3 returned 1 evidence-gated supplier(s) (P@5=0.00, CSR=0.77).

