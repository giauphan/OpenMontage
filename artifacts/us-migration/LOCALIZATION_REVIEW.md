# Localization & Editorial Review — OpenMontage US Migration

## 1. Editorial Philosophy: Grounded Native Storytelling vs. Machine Translation

The transition from Vietnamese to US-first English cannot rely on automated translation of existing Vietnamese scripts. Vietnamese tech scripts typically follow an informational-summary structure with honorific transitions and formal phrasing that sounds stiff, robotic, and disengaging to American tech audiences.

The US-first editorial contract mandates:
1. **Hook-First Narrative Arc**: Grabbing attention in the first 2 seconds by highlighting a universal developer pain point or striking industry shift.
2. **Point-Proof-Payoff Flow**: Rapidly delivering the core revelation, proving it with concrete evidence (benchmarks, UI recordings, primary documentation), and capping it with a practical takeaway.
3. **Idiomatic Precision**: Using natural American tech colloquialisms ("vanished", "token budget", "dial thinking up or down") without adopting vacuous marketing jargon.
4. **Canadian Secondary Nuance**: Respecting North American regional terms (avoiding US-only pricing assumptions without qualification).

---

## 2. Editorial Scorecard Rubric

| Criterion | Target | Short Canary (`canary-short-en-us-01`) | Longform Canary (`canary-longform-en-us-02`) | Status |
|---|---|---|---|---|
| **Hook Effectiveness** | >= 8.5/10 | 9.5 / 10 | 9.0 / 10 | PASS |
| **Native Idiomatic Phrasing** | >= 9.0/10 | 9.8 / 10 | 9.6 / 10 | PASS |
| **Claim Binding & Evidence Fidelity** | 10.0 / 10 (Strict) | 10.0 / 10 | 10.0 / 10 | PASS |
| **Technical Nomenclature Accuracy** | >= 9.5/10 | 10.0 / 10 | 10.0 / 10 | PASS |
| **Pacing & Information Density** | >= 8.5/10 | 9.2 / 10 | 9.4 / 10 | PASS |
| **Cultural & Regional Nuance** | >= 9.0/10 | 9.5 / 10 | 9.5 / 10 | PASS |
| **Overall Weighted Score** | **>= 9.0/10** | **9.67 / 10** | **9.58 / 10** | **PASS** |

---

## 3. Canary 1 Editorial Analysis (`canary-short-en-us-01`)

### Topic
**Anthropic Releases Claude 3.7 Sonnet with Hybrid Reasoning**

### Script Evaluation

- **Scene 1 (Hook - 0:00 to 0:03)**:
  - *Draft Phrasing (Literal translation of VN script)*: "Today Anthropic company introduces model Claude 3.7 Sonnet with new hybrid thinking function." (REJECTED: flat, unengaging, machine-translated cadence).
  - *Approved US Copy*: *"Ever wonder why AI models force you to choose between speed and deep reasoning?"*
  - *Editorial Note*: Posits a direct problem that every LLM developer experiences daily.
- **Scene 2 (Point - 0:03 to 0:06)**:
  - *Approved US Copy*: *"That trade-off just vanished with Anthropic's new Claude 3.7 Sonnet."*
  - *Editorial Note*: Punchy, active verb ("vanished"), immediately answers the hook.
- **Scene 3 (Proof - 0:06 to 0:09)**:
  - *Approved US Copy*: *"With hybrid reasoning, you set the thinking budget: near-instant answers or extended reflection."*
  - *Editorial Note*: Accurately introduces the official technical concept ("thinking budget") backed by Claim C002.
- **Scene 4 (Payoff - 0:09 to 0:12)**:
  - *Approved US Copy*: *"One unified model for both quick chats and hard technical coding. Follow for daily AI breakdowns."*
  - *Editorial Note*: Concrete payoff for engineers, non-intrusive call to action.

### Language Purity Audit
- Vietnamese diacritics detected: **0**
- Foreign loan words / Vietnamese stop-words: **0**
- Title hashtag compliance: `#ai #tech #anthropic #claude #Shorts` (100% compliant)

---

## 4. Canary 2 Editorial Analysis (`canary-longform-en-us-02`)

### Topic
**How Latent Diffusion Transformers Work: From Noise to High-Fidelity Video**

### Script Evaluation

- **Scene 1 (Hook - 0:00 to 0:04)**:
  - *Approved US Copy*: *"Modern generative video discarded convolutional U-Nets in favor of Diffusion Transformers."*
  - *Editorial Note*: Establishes immediate authority and sets the historical shift clearly.
- **Scene 2 (Point - 0:04 to 0:08)**:
  - *Approved US Copy*: *"Instead of downsampling feature maps, the model splits latent video representations into sequential patches."*
  - *Editorial Note*: Explains patchification simply and mathematically correctly without condescension.
- **Scene 3 (Proof - 0:08 to 0:12)**:
  - *Approved US Copy*: *"Conditioning happens through adaptive layer norm zero, stabilizing training from the start."*
  - *Editorial Note*: Cites the exact architectural mechanism (adaLN-Zero) with mathematical provenance from Peebles & Xie (2022).
- **Scene 4 (Payoff - 0:12 to 0:16)**:
  - *Approved US Copy*: *"This architectural simplicity explains why modern video generators scale predictably with compute."*
  - *Editorial Note*: Ties technical detail back to the broader industry significance (compute scaling laws).

---

## 5. Reviewer Sign-Off

The editorial review confirms that both scripts are authentic, idiomatically sound, factually verified, and culturally calibrated for the US tech developer and creator audience.
