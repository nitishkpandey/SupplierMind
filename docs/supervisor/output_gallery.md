# Output Gallery — Three Paradigms Side by Side

Benchmark run `77e41957-9464-4883-860f-fe76155eed06` (GPT-4o-mini, 2026-06-13).
Five representative queries; per paradigm: returned suppliers, the
reasoning/evidence it produced, latency and cost. Built by
`backend/scripts/build_output_gallery.py`, no manual edits to outputs.

---

## Q1 (simple): “Find metal suppliers in Germany”

Ground truth: 5 matching supplier(s) in the corpus.

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 3.5s · $0.0001*

**Returned:**
- Thyssenkrupp AG *(not in corpus)*
- Salzgitter AG *(not in corpus)*
- Klockner & Co SE *(not in corpus)*
- Aalberts N.V. *(not in corpus)*
- Metallbau GmbH *(not in corpus)*

**Model reasoning:**

> One of the largest steel producers in Germany, Thyssenkrupp offers a wide range of metal products and services.; A major player in the steel industry, Salzgitter AG provides various metal products and has a strong presence in Germany.; A leading metal distributor in Europe, Klockner & Co offers a variety of metals and services across Germany.; Specializes in advanced metal solutions and has operations in Germany, providing high-quality metal products.; A local supplier known for custom metal fabrication and a range of metal products tailored to specific needs.

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.20 · MRR 1.00 · CSR 1.00 · 5.0s · $0.0003*

**Returned:**
- Duesseldorf Metals AG
- Düsseldorf Metals GmbH & Co. KG
- Dortmund Metals GmbH & Co. KG
- Cologne Metals AG
- Cologne Foundry GmbH & Co. KG

**Model reasoning:**

> Duesseldorf Metals AG is located in Düsseldorf, Germany, and specializes in precision metal components including steel, aluminum, and copper alloys. It has ISO certifications and a significant monthly capacity.; Düsseldorf Metals GmbH & Co. KG is also based in Düsseldorf, Germany, and manufactures precision metal components. Although it lacks certifications, it serves key industries and has a reasonable capacity.; Dortmund Metals GmbH & Co. KG is located in Dortmund, Germany, and has a high capacity for manufacturing precision metal components. It serves multiple industries, making it a strong…

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.75 · 59.6s · $0.0045*

**Returned:**
- Frankfurt Steel GmbH & Co. KG
- Dortmund Alloys AG
- Dortmund Steel GmbH
- Munich Steel GmbH & Co. KG
- Düsseldorf Alloys AG

**Per-constraint verdicts:**
- **Frankfurt Steel GmbH & Co. KG** — 3/4 constraints PASS; failed: OHSAS 18001: ISO 45001 supersedes OHSAS 18001, indicating a related certification. [unverified: quote_unverifiable]
- **Dortmund Alloys AG** — 3/4 constraints PASS; failed: OHSAS 18001: ISO 45001 is a related certification that supersedes OHSAS 18001.
- **Dortmund Steel GmbH** — 3/4 constraints PASS; failed: OHSAS 18001: The supplier does not hold OHSAS 18001 or any directly equivalent certification.
- **Munich Steel GmbH & Co. KG** — 3/4 constraints PASS; failed: OHSAS 18001: The supplier does not hold OHSAS 18001 or any related certification.
- **ed2cb08b-e1e9-c802-bd1e-b0481db6e10f** — 2/4 constraints PASS; failed: ISO 14001: Supplier does not hold ISO 14001 or any related certification.; OHSAS 18001: Supplier does not hold OHSAS 18001 or any related certification.
- **Düsseldorf Alloys AG** — 2/4 constraints PASS; failed: AS9100: IATF 16949 is explicitly not equivalent to AS9100; OHSAS 18001: The supplier does not hold any related certification to OHSAS 18001.
- **6957597b-dd26-0497-b9e1-550dec74352d** — 2/4 constraints PASS; failed: AS9100: Supplier does not hold AS9100 or any directly equivalent certification.; OHSAS 18001: Supplier does not hold OHSAS 18001 or any related certification.
- **dbd90ecb-c6b0-a217-b8b1-166e00f4dde2** — 1/4 constraints PASS; failed: ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001; AS9100: Supplier does not hold AS9100 or any equivalent certification.
- **6e96c57c-493a-e137-ee93-5ad336f58528** — 1/4 constraints PASS; failed: ISO 14001: ISO 9001 is explicitly not equivalent to ISO 14001; AS9100: Supplier does not hold AS9100 or any related certification.
- **Düsseldorf Metals GmbH & Co. KG** — 0/4 constraints PASS; failed: ISO 9001: Supplier lists no certifications; ISO 9001 required; ISO 14001: Supplier lists no certifications; ISO 14001 required

**Observation:** P1 produced five plausible real-world companies (Thyssenkrupp,
Salzgitter…) — none exist in the corpus; the names come from parametric memory,
not the data. P2 scores a perfect CSR here because the query has only two
trivial constraints (category + country) that retrieval satisfies by
construction. P3's verdicts reveal a parser defect worth noting: the query asks
only for "metal suppliers in Germany", yet the agent checked four certification
constraints (ISO 9001/14001, AS9100, OHSAS 18001) it extracted from nowhere —
over-extraction that drives the simple-tier CSR penalty and the over-filtering
seen across the simple tier.

---

## Q10 (medium): “Electronics supplier in Germany with ISO 9001 and RoHS, lead time under 30 days”

Ground truth: 1 matching supplier(s) in the corpus.

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 9.1s · $0.0002*

**Returned:**
- RS Components *(not in corpus)*
- Farnell *(not in corpus)*
- Digi-Key Electronics *(not in corpus)*
- Mouser Electronics *(not in corpus)*
- Conrad Electronic *(not in corpus)*

**Model reasoning:**

> RS Components is a well-known electronics supplier in Germany that offers a wide range of electronic components and has ISO 9001 certification. They also comply with RoHS regulations and typically have lead times under 30 days.; Farnell is a reputable distributor of electronic components in Germany, known for their quality assurance with ISO 9001 certification. They provide RoHS compliant products and generally maintain a lead time of less than 30 days.; Digi-Key is a global supplier with a strong presence in Germany, offering a vast selection of electronic components. They are ISO 9001 certif…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.00 · MRR 0.00 · CSR 0.71 · 4.0s · $0.0002*

**Returned:**
- Cologne Electronics GmbH
- Cologne Electronics GmbH & Co. KG
- Dortmund Electronics GmbH
- Hamburg Electronics AG

**Model reasoning:**

> Cologne Electronics GmbH has both ISO 9001 and RoHS certifications, and is based in Germany.; Cologne Electronics GmbH & Co. KG holds ISO 9001 and RoHS certifications, and is located in Germany.; Dortmund Electronics GmbH has ISO 9001 and RoHS certifications, and operates in Germany.; Hamburg Electronics AG holds ISO 9001 certification and is based in Germany, although it does not explicitly mention RoHS compliance.

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.20 · MRR 0.33 · CSR 1.00 · 27.0s · $0.0016*

**Returned:**
- Dortmund Electronics GmbH & Co. KG
- Cologne Electronics GmbH
- Bremen Electronics AG
- Hamburg Circuits GmbH
- Munich Circuits GmbH & Co. KG

**Per-constraint verdicts:**
- **Bremen Electronics AG** — 3/3 constraints PASS
- **Hamburg Circuits GmbH** — 3/3 constraints PASS
- **Munich Circuits GmbH & Co. KG** — 3/3 constraints PASS
- **be274090-3d15-ac48-f33c-8030e772611b** — 3/3 constraints PASS
- **Dortmund Electronics GmbH & Co. KG** — 3/3 constraints PASS
- **Cologne Electronics GmbH** — 2/2 constraints PASS
- **17d5b563-fa60-ede1-e5eb-772df11c0ac5** — 2/3 constraints PASS; failed: lead_time: Lead time 42d exceeds 29d limit
- **Cologne Electronics GmbH & Co. KG** — 2/3 constraints PASS; failed: lead_time: Lead time 44d exceeds 29d limit
- **26a5c409-aa62-6e52-35ef-4c165ca83b82** — 1/3 constraints PASS; failed: ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001; lead_time: Lead time 44d exceeds 29d limit
- **0b79c9b7-3887-d536-677e-33954d12025f** — 1/3 constraints PASS; failed: ISO 9001: The supplier does not hold the ISO 9001 certification or any related certification.; lead_time: Lead time 48d exceeds 29d limit

**Observation:** This is P3's home turf — multi-constraint with real ground
truth. P3 returned five suppliers, all verified 3/3 compliant (CSR 1.00), with
the ground-truth supplier at rank 3 (MRR 0.33). P2 returned only four picks,
one of which it *admits* lacks RoHS in its own reasoning yet includes anyway
(CSR 0.71) — grounded but not gated. P1 named five real distributors
(RS Components, Digi-Key…) that don't exist in the corpus, with confident
fabricated compliance claims for each.

---

## Q14 (medium): “Packaging manufacturer with 50000+ units per month capacity in Netherlands”

Ground truth: 3 matching supplier(s) in the corpus.

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 3.0s · $0.0001*

**Returned:**
- Smurfit Kappa *(not in corpus)*
- Mondi Group *(not in corpus)*
- VPK Packaging *(not in corpus)*
- DS Smith *(not in corpus)*
- Sappi Lanaken Mill *(not in corpus)*

**Model reasoning:**

> A leading provider of paper-based packaging solutions with multiple facilities in the Netherlands, capable of high-volume production.; An international packaging and paper group with operations in the Netherlands, known for their large-scale manufacturing capabilities.; A prominent packaging manufacturer in Europe with a strong presence in the Netherlands, offering high-capacity production lines.; A global leader in sustainable packaging solutions, with significant manufacturing capacity in the Netherlands to meet large orders.; Part of the Sappi Group, this mill in the Netherlands specializes…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.40 · MRR 0.50 · CSR 1.00 · 3.1s · $0.0002*

**Returned:**
- Amsterdam Packaging N.V.
- Amsterdam Packaging B.V.
- Rotterdam Packaging GmbH

**Model reasoning:**

> Amsterdam Packaging N.V. has a capacity of 192770 units/month, which exceeds the required capacity and is located in the Netherlands.; Amsterdam Packaging B.V. has a capacity of 193560 units/month, which exceeds the required capacity and is located in the Netherlands.; Rotterdam Packaging GmbH has a capacity of 304433 units/month, which exceeds the required capacity and is located in the Netherlands.

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.48 · 50.3s · $0.0046*

**Returned:**
- Amsterdam Packaging N.V.
- Rotterdam Packaging B.V.
- Utrecht Container B.V.
- Eindhoven Packaging B.V.
- Utrecht Container N.V.

**Per-constraint verdicts:**
- **Amsterdam Packaging N.V.** — 3/5 constraints PASS; failed: FSC Certification: PEFC is explicitly not equivalent to FSC; BRCGS Packaging: The supplier does not hold any certification equivalent or related to BRCGS Packaging.
- **Utrecht Container B.V.** — 2/5 constraints PASS; failed: FSC Certification: PEFC is explicitly not equivalent to FSC; BRCGS Packaging: The supplier does not hold any certification equivalent or related to BRCGS Packaging.
- **Rotterdam Packaging B.V.** — 2/5 constraints PASS; failed: FSC Certification: PEFC is explicitly not equivalent to FSC; BRCGS Packaging: The supplier does not hold any related certification to BRCGS Packaging.
- **Utrecht Container N.V.** — 2/5 constraints PASS; failed: FSC Certification: The supplier mentions a supply chain that is FSC-certified, indicating a related certification.; BRCGS Packaging: No related certification found for BRCGS Packaging.
- **Eindhoven Packaging B.V.** — 2/5 constraints PASS; failed: FSC Certification: PEFC is explicitly not equivalent to FSC; BRCGS Packaging: ISO 22000 is explicitly not equivalent to BRC
- **1664d782-b01c-31e3-f8d3-f4370b9b3bd9** — 2/6 constraints PASS; failed: country: Supplier is in Belgium, required country is Netherlands; FSC Certification: PEFC is explicitly not equivalent to FSC
- **6f790fe1-64f5-25e2-8e0c-517c1ab17d2a** — 1/5 constraints PASS; failed: ISO 14001: ISO 9001 is explicitly not equivalent to ISO 14001; FSC Certification: The supplier holds the FSC certification, which is directly equivalent. [downgraded: quote_too_short]
- **2f23654f-3e47-5bfa-29f1-72600eb68a13** — 1/5 constraints PASS; failed: ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001; FSC Certification: The supplier mentions a supply chain that is FSC-certified, indicating a related certification.
- **a08d4c99-6b8e-1e76-d132-38991c08b092** — 1/5 constraints PASS; failed: ISO 14001: ISO 9001 is explicitly not equivalent to ISO 14001; FSC Certification: The supplier mentions a supply chain that is FSC-certified, indicating a related certification.
- **eac48320-48e9-8195-0984-f72b09e6d5b0** — 0/5 constraints PASS; failed: ISO 9001: Supplier lists no certifications; ISO 9001 required; FSC Certification: Supplier lists no certifications; FSC Certification required

**Observation:** P2's best query — it returned exactly the right three
suppliers (P@5 0.40 = 2 of its picks in the 3-supplier ground truth, CSR 1.00)
by reading capacity numbers straight from retrieved profiles. P3 shows the
same over-extraction defect as Q1: the query has two constraints (category +
capacity + country), but the agent invented FSC and BRCGS certification
requirements and then penalised every candidate for failing them — turning an
easy win into CSR 0.48. The agent's strictness is only as good as its
constraint parser.

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

> Mondi is a global leader in packaging and paper, with facilities in Europe, including near Berlin. They have ISO 9001 certification and the capacity to produce large volumes quickly.; Smurfit Kappa specializes in paper-based packaging solutions and has a strong presence in Europe. They are ISO 9001 certified and can meet high-volume demands efficiently.; DS Smith is known for sustainable packaging solutions and operates in the European market. They have ISO 9001 certification and the capability to deliver large quantities within tight timelines.; Schumacher Packaging is a prominent packaging m…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.00 · MRR 0.00 · CSR 0.27 · 3.0s · $0.0003*

**Returned:**
- Berlin Packaging GmbH
- Berlin Pack Solutions GmbH
- Berlin Pack Solutions AG
- Berlin Packaging GmbH & Co. KG
- Berlin Pack Solutions GmbH & Co. KG

**Model reasoning:**

> Berlin Packaging has a capacity of 117586 units/month, holds ISO 14001 certification, and is located in Berlin, making it a strong candidate for high-volume packaging needs.; Berlin Pack Solutions GmbH has ISO 9001 certification and a capacity of 2322 units/month, which is relevant but does not meet the volume requirement.; Berlin Pack Solutions AG holds ISO 9001 certification and is located in Berlin, but its capacity of 1383 units/month is below the required threshold.; Berlin Packaging GmbH & Co. KG has ISO 9001 certification and a capacity of 582 units/month, which is insufficient for the …

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.40 · 40.2s · $0.0021*

**Returned:**
- *(no suppliers returned)*

**Per-constraint verdicts:**
- **60aa90aa-2a65-4958-b19a-71c1d3f72643** — 1/3 constraints PASS; failed: country: Supplier is in Global, required country is Berlin; capacity: Capacity data not available in supplier profile
- **c7fdc27a-4af2-4ba5-9701-4aad5be7037d** — 1/3 constraints PASS; failed: country: Supplier is in USA, required country is Berlin; capacity: Capacity data not available in supplier profile
- **Berlin Packaging GmbH** — 1/3 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001
- **Berlin Packaging GmbH & Co. KG** — 1/3 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity 582 units/month is below minimum 100,000
- **Berlin Pack Solutions AG** — 1/3 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity 1,383 units/month is below minimum 100,000
- **Berlin Pack Solutions GmbH** — 1/3 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; capacity: Capacity 2,322 units/month is below minimum 100,000
- **67f632d1-c873-4280-906d-52f22b9b60cf** — 0/3 constraints PASS; failed: country: Supplier is in Global, required country is Berlin; ISO 9001: Supplier lists no certifications; ISO 9001 required
- **2cca6c97-ff93-4399-b4fc-df1a81c4f5e5** — 0/3 constraints PASS; failed: country: Supplier is in USA, required country is Berlin; ISO 9001: CE is explicitly not equivalent to ISO 9001
- **a1aec478-6f9f-4c5a-b14e-7cf90308cdae** — 0/3 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; ISO 9001: Supplier lists no certifications; ISO 9001 required
- **Berlin Pack Solutions GmbH & Co. KG** — 0/3 constraints PASS; failed: country: Supplier is in Germany, required country is Berlin; ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001

**Observation:** The headline behaviour of the whole gallery. No supplier in
the corpus satisfies all constraints — the correct answer is the empty set.
**P3 is the only paradigm that returned nothing**, with per-candidate verdicts
documenting exactly why each of ten candidates fails (capacity 582 vs 100,000
minimum, ISO 14001 ≠ ISO 9001, …). P1 confidently named five real companies.
P2 returned five Berlin suppliers, four of which its own reasoning admits fail
the volume requirement. Caveat: P3's location verdict ("required country is
Berlin") shows the parser mapped the 40 km radius onto the *country* field —
right refusal, partly for a malformed reason.

---

## Q19 (hard): “ISO 9001 certified bronze supplier within 50km of Bremen, 3000+ kg/month, lead time under 21 days”

Ground truth: 0 matching supplier(s) in the corpus. **No supplier satisfies all constraints — correct answer is the empty set.**

### P1 — Single prompt (parametric memory)

*P@5 0.00 · MRR 0.00 · CSR 0.00 · 3.8s · $0.0002*

**Returned:**
- Bronze Alloys GmbH *(not in corpus)*
- Metallwerk Bremen AG *(not in corpus)*
- Bremen Bronze Foundry *(not in corpus)*
- Hermann Müller GmbH *(not in corpus)*
- Norddeutsche Metallwerke *(not in corpus)*

**Model reasoning:**

> Located near Bremen, this supplier specializes in bronze alloys and is ISO 9001 certified, capable of meeting high volume demands.; This company is known for its metal production and processing, including bronze, and holds ISO 9001 certification, with a strong local presence.; A local foundry that produces bronze components and is ISO 9001 certified, they can handle large orders with quick lead times.; This supplier offers a range of metal products, including bronze, and is ISO 9001 certified, with the capacity to fulfill large monthly orders.; Located within the Bremen area, they specialize i…

### P2 — RAG (retrieve top-10, one prompt)

*P@5 0.00 · MRR 0.00 · CSR 0.83 · 2.0s · $0.0002*

**Returned:**
- Bremen Forge AG
- Bremen Forge GmbH & Co. KG

**Model reasoning:**

> Bremen Forge AG is ISO 9001 certified, has a capacity of 9399.0 kg/month, and is located in Bremen, meeting all the user's requirements.; Bremen Forge GmbH & Co. KG is ISO 9001 certified, has a capacity of 60460.0 kg/month, and is located in Bremen, fulfilling the user's criteria.

### P3 — SupplierMind (agentic, evidence-gated)

*P@5 0.00 · MRR 0.00 · CSR 0.62 · 30.9s · $0.0016*

**Returned:**
- Bremen Forge GmbH & Co. KG
- Bremen Forge AG
- Bremen Metals GmbH
- Bremen Steel GmbH
- Bremen Alloys GmbH

**Per-constraint verdicts:**
- **Bremen Forge AG** — 3/4 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen
- **Bremen Forge GmbH & Co. KG** — 3/4 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen
- **Bremen Steel GmbH** — 2/4 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; capacity: Capacity data not available in supplier profile
- **45f363f4-a981-12a3-94e1-90ac0a1e9f2c** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; capacity: Capacity data not available in supplier profile
- **ca3a9d86-1293-78ad-1dfe-cb1f0c202f49** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; ISO 9001: ISO 45001 is explicitly not equivalent to ISO 9001
- **Bremen Alloys GmbH** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; ISO 9001: Supplier lists no certifications; ISO 9001 required
- **750cc421-ab19-154a-1faf-f912803f5ca4** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; ISO 9001: Supplier lists no certifications; ISO 9001 required
- **Bremen Metals GmbH** — 2/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; capacity: Capacity 1,739 kg/month is below minimum 3,000
- **cf8a0484-53bc-5eb5-95eb-8bf65fd779ae** — 1/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001
- **6f1d6ebe-96ea-aabf-78d4-f7d0995635dc** — 1/5 constraints PASS; failed: country: Supplier is in Germany, required country is Bremen; ISO 9001: ISO 14001 is explicitly not equivalent to ISO 9001

**Observation:** The other impossible query, and here P3 did *not* refuse — it
returned five Bremen suppliers, unlike its correct empty set on Q23. The same
city-as-country parser artifact ("Supplier is in Germany, required country is
Bremen") fails every candidate's location check, yet the agent still ranked
and returned them. Refusal behaviour on impossible queries is inconsistent
(1 of 2 in this gallery). P1 fabricated five plausible German foundries,
including a fictitious "Bremen Bronze Foundry". P2 returned two real Bremen
forges that pass everything except the unstatable 50 km radius — defensible
picks, no refusal capability at all.

