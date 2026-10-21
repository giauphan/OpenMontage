# YouTube Studio Rebrand & Channel Preservation Checklist (P1)

**Owner / Creator Guide for US-First English Transition**  
**Repository:** `giauphan/OpenMontage`  
**Host Context:** Phoenix, Arizona (Dedicated execution host; no VPN or server change required)  
**Safety Status:** Manual owner operations in YouTube Studio only. Zero automated deletion or channel mutation via code.

---

## 1. Channel ID & Historical Preservation (DO FIRST)

- [ ] **Record and Verify Channel ID**:
  - In YouTube Studio -> **Settings** -> **Channel** -> **Advanced settings** -> **Manage YouTube account** -> **Advanced settings**, copy your **Channel ID** (starts with `UC...`).
  - **Hard Rule**: This ID will NOT change during rebranding. The publisher code will enforce an authenticated channel ID match against this exact ID before allowing any media upload.
- [ ] **Export Video Inventory & Analytics**:
  - In Studio -> **Content**, export table data (Video ID, Title, Visibility, Views, Watch Time, Publish Date).
  - Save this CSV offline. If an old video is ever needed or questioned, this is your immutable ledger.
- [ ] **Backup Original Branding**:
  - Save current channel name, handle (`@...`), avatar, banner image, and Vietnamese "About" description to local disk.

---

## 2. Legacy Vietnamese Content: Manual Unlisting Policy

- [ ] **Unlist Old Vietnamese Shorts (DO NOT DELETE)**:
  - Select historical Vietnamese Shorts in Studio -> **Content**.
  - Set Visibility to **Unlisted** (or do this progressively).
  - **Why Never Delete?**
    1. Deleting videos deletes their analytics history, channel watch-time history, and established trust signals with YouTube's abuse prevention systems.
    2. Deleting videos breaks external inbound links, playlists, and viewer bookmarks.
    3. Setting to **Unlisted** hides the videos from your channel home page, search results, and feed recommendations, allowing the algorithm to calibrate fresh impressions exclusively on new English content.
  - **YPP Policy Note**: Unlisted Short views do not count towards the 90-day 10M Short view threshold for YouTube Partner Program (YPP), but neither would deleted ones. Existing public view totals will recede from public stats, which is expected during a pivot.

---

## 3. Channel Branding & US-First Positioning

- [ ] **Channel Name & Handle**:
  - Change channel name to an English-first title reflecting the new positioning (e.g., focused on practical AI, developer tools, and workflow automation).
  - Update channel handle (`@...`) if desired and available.
- [ ] **Channel Description ("About" Section)**:
  - Replace Vietnamese bio with a concise, professional American-English description.
  - Focus on value proposition for US viewers:
    - *Example*: "Hands-on testing and practical breakdowns of new AI tools, developer workflows, and agentic systems. We test real capabilities, benchmark claims against primary sources, and show you exactly what works."
  - Include official business inquiries contact email and relevant links (GitHub, documentation).
- [ ] **Visual Assets (Banner & Profile)**:
  - Upload an English-language banner (recommended 2048 x 1152 px, safe area 1235 x 338 px).
  - Update channel icon / avatar if branding has evolved.
- [ ] **Featured Content**:
  - Clear out Vietnamese featured trailer / featured video for returning subscribers until the first approved English canaries are published.

---

## 4. YouTube Studio Upload Defaults & Channel Settings

- [ ] **Default Video Language**:
  - In Studio -> **Settings** -> **Upload defaults** -> **Advanced settings**:
    - **Video language**: `English (United States)`
    - **Title and description language**: `English (United States)`
    - **Caption certification**: "This content has never aired on television in the U.S. with captions" (or "None")
- [ ] **Audience & Made for Kids**:
  - In Studio -> **Settings** -> **Channel** -> **Advanced settings**:
    - Select: *"No, set this channel as not made for kids. I never upload content that's made for kids."*
    - Note: This is an audience classification requirement under COPPA and YouTube policy, not a demographic judgment.
- [ ] **Synthetic / Altered Content Defaults**:
  - In Studio, review the policy on synthetic and altered content.
  - When uploading content containing photorealistic AI-generated scenes or synthetic voices depicting real events, YouTube requires checking the "Altered content" disclosure box.
  - OpenMontage metadata schemas will explicitly enforce this disclosure (`containsSyntheticMedia`).

---

## 5. Tax, Residence, and Account Facts (NEVER FALSIFY)

- [ ] **Maintain Authentic Account Facts**:
  - **Country of Residence**: Keep your real, legal country of residence in AdSense and tax settings.
  - **Tax Information (W-8BEN)**: Maintain your actual tax treaty status.
  - **Do NOT attempt to spoof or fake US residency or US tax status**: YouTube distributes content globally and tailors recommendations based on *viewer* engagement and language signals, not creator location or upload IP.
  - Falsifying tax or residence information risks permanent AdSense termination and account disabling.

---

## 6. Preflight Verification Before Next Automated Stage

- [ ] Channel ID recorded: `UC...` (stored securely in environment / vault as `EXPECTED_CHANNEL_ID`).
- [ ] All old Vietnamese Shorts marked **Unlisted** (not deleted).
- [ ] Channel visual branding and description updated to English.
- [ ] Upload default language set to `English (United States)`.
- [ ] No VPN or IP manipulation tools active.
