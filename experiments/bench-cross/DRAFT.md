# Cross-paper questions: DRAFT, not frozen (2026-10-20)

Over the 10 battery papers of `runs/papers-corpus` (cai2026 left out). Questions never name the paper; the answer
must find it. Facts come from the verified keys of bench-leads / bench-multistep unless marked NEW. Before freezing:
write probes.json (id, cat, q, expect, must, must_not, trap), check every NEW fact in the text, hash-freeze.

Verified so far (grep over direct-text/): "Cyrene" only in susmat-2020 (61) and mattod-2020 (1, ref [129]);
"BatPaC/BatPac" in adma-2020, aenm-2022, ensm-2020; "tap density" once in aenm-2022 (read it before any absence
question); ensm-2020 cites the DOE cell cost target $80/kWh (lines 31, 149); mattod-2020 says EG delaminates
"in seconds ... nor corroding the Al foil [121]", PVDF not removed; Cyrene reclaims cathode, Al foil and PVDF [129].

W (which paper): 65.7% after 1000 cycles -> cssc-2020, 1.4 Ah pouch | Na nucleation overpotential on Al -> nl74,
19 to 12 mV | cobalt for 1M EVs -> adma-2020, ~2500 t NMC111, ~700 t NMC811/NCA | recycling market -> mattod,
$12.2bn->$18.1bn, 8.2% | 92.67% of baseline -> susmat, 40 cycles C/3, 158.0 | NMC532 moisture -> ensm-2020, 625 vs
200 ppm | NiTi wires -> acsnano, 5% and 10% | coating diffusivity table -> ensm-2021, TiO2 rutile 1e-6.
C (compare): glymes: nl72 tetraglyme, nl74 diglyme (NaPF6) | 100 C separation: EG <2 min (cssc) vs Cyrene 1 h
(susmat) | PVDF: EG leaves it (cssc), Cyrene dissolves/reclaims it (susmat) | Li leaching: EG 1.015->0.993 (cssc),
Cyrene ether groups, numbers only in Table S1 (susmat), water ~3 wt%/week (ensm-2020) | cost: DOE $80/kWh
(ensm-2020) vs ~$130/kWh in 2020 (aenm): $50 above | half cells only (susmat) vs 1.4 Ah pouch (cssc).
K (count): sodium-battery papers = 2 (nl72, nl74) | papers mentioning Cyrene = 2 | papers mentioning BatPaC = 3.
H (chain): mattod's "in seconds" solvent -> EG, ~2 s at 198 C (cssc) | mattod's green solvent -> Cyrene, DSC ~90 C
(susmat) | NFA: 72% after 200 cycles 0.5 Ah pouch (aenm) + NFA-A best ~80% (adma) | ensm-2020 Table 1 Co-free
250-275 Wh/kg + NFA-A ~192 mAh/g (adma) | NMC622 ~30% of cell weight (mattod) + 194.0 mAh/g recovered (susmat).
X (compute): NFA 811 ~205 (adma) - LFP 170 (aenm) = 35 | ~400 Wh/kg (nl74) - 350 (ensm-2020 Table 1 top) = 50
| 194.0 (susmat) - LCO ~140 (aenm) = 54 | ~2 Mt usable Co (aenm) / 2500 t per 1M EVs NMC111 (adma) = 800.
A (absence): Cyrene price | EG process cost per kg | full-cell retention of Cyrene-recovered NMC622 (future work).
F (false premise): both sodium papers use carbonates (no: glymes) | both solvent papers dissolve PVDF (no: only
Cyrene) | NFA pouch cells failed before 100 cycles (no: 72% at 200) | EG corrodes Al foil (no: cssc, mattod).

Arms planned (Llama only, no Haiku): ugrc corpus + Jev leads (needs a corpus form of ask.SYSTEM_SMALL: it raises
ValueError today), ugrc corpus plain, papers pasted in up to ~120k tokens chosen by retrieval, and the hybrid
(code/Jev retrieve, Llama reads, code cites).
