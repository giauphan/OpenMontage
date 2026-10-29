#!/usr/bin/env python3
"""Native YouTube scheduler with Instagram claims for slot cron.
Filters queued projects by publish_date == --date. Usage: --date YYYY-MM-DD (default today VN).
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(os.environ.get("OPENMONTAGE_ROOT") or Path(__file__).resolve().parents[1])
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.publish_config import (
    load_config,
    publish_timezone,
    canonical_platform_name,
    get_held_platforms,
    is_platform_held,
    get_enabled_platforms,
    is_platform_enabled,
)
from scripts.validate_publish_metadata import validate_metadata
from tools.news import template_provenance
from tools.publish_store import PublishStore, publish_key
from tools.publishers.platform_routes import (
    youtube_shorts_title,
    compose_release_metadata,
)
from tools.publishers.youtube_publisher import YoutubePublisher


def build_youtube_payload(
    topic_meta: dict,
    video_path: str,
    publish_at: str | None = None,
    thumbnail_path: str | None = None,
) -> dict:
    """Build unified YouTube upload payload using compose_release_metadata."""
    # Ensure id/title/desc exist for compose
    payload_meta = dict(topic_meta)
    if "id" not in payload_meta:
        payload_meta["id"] = payload_meta.get("project_id", "news_video")
    rel = compose_release_metadata(payload_meta)
    yt = rel.youtube_payload
    payload = {
        "video_path": str(video_path),
        "title": yt["title"],
        "description": yt["description"],
        "tags": yt["tags"],
        "privacy_status": "private" if publish_at else "unlisted",
        "publish_at": publish_at,
        "category_id": "28",
        "format": payload_meta.get("format", "short"),
        "locale": payload_meta.get("locale") or os.environ.get("OPENMONTAGE_LOCALE") or "en-US",
    }
    expected_channel = (
        payload_meta.get("expected_channel_id")
        or os.environ.get("EXPECTED_CHANNEL_ID")
        or os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID")
    )
    if expected_channel:
        payload["expected_channel_id"] = expected_channel
    if "contains_synthetic_media" in payload_meta:
        payload["contains_synthetic_media"] = payload_meta["contains_synthetic_media"]

    # Thumbnail resolution (explicit arg -> topic_meta -> project discovery -> JIT generation)
    thumb = thumbnail_path or payload_meta.get("thumbnail_path") or payload_meta.get("thumbnail")
    if not thumb or not Path(thumb).is_file():
        v_p = Path(video_path)
        candidates = [
            v_p.parent.parent / "artifacts" / "thumbnail.png",
            v_p.parent.parent / "artifacts" / "thumbnail.jpg",
            v_p.parent / "artifacts" / "thumbnail.png",
            v_p.parent / "artifacts" / "thumbnail.jpg",
            v_p.parent.parent / "thumbnails" / "thumbnail.png",
            v_p.parent.parent / "thumbnails" / "thumbnail.jpg",
            v_p.parent / "thumbnail.png",
            v_p.parent / "thumbnail.jpg",
            v_p.parent / "thumbnails" / "thumbnail.png",
            v_p.parent / "thumbnails" / "thumbnail.jpg",
        ]
        for c in candidates:
            if c.is_file():
                thumb = str(c)
                break

    # If still missing, empty, or placeholder (< 50KB), attempt just-in-time generation
    if not thumb or not Path(thumb).is_file() or Path(thumb).stat().st_size < 50_000:
        try:
            from lib.news_visual.thumbnail_orchestrator import ThumbnailOrchestrator
            v_p = Path(video_path)
            pdir = v_p.parent.parent if v_p.parent.name == "renders" else v_p.parent
            if pdir.is_dir() and pdir.name.startswith("cand_"):
                title = payload_meta.get("title") or pdir.name
                res = ThumbnailOrchestrator.generate_thumbnail(
                    project_dir=pdir,
                    title=title,
                    topic=payload_meta.get("topic", "") or payload_meta.get("summary", ""),
                    format_type=payload_meta.get("format", "short"),
                    allow_fallback=True,
                )
                if res.success and res.thumbnail_path and Path(res.thumbnail_path).is_file():
                    thumb = res.thumbnail_path
        except Exception:
            pass

    if thumb and Path(thumb).is_file():
        payload["thumbnail_path"] = str(thumb)

    return payload


def make_publish_datetime(d: date, time_str: str, tz: ZoneInfo) -> datetime:
    """Create a timezone-aware datetime with robust DST gap and fold resolution."""
    hh, mm = time_str.split(":", 1)
    naive = datetime.combine(d, datetime.strptime(f"{hh}:{mm}", "%H:%M").time())
    dt = naive.replace(tzinfo=tz)
    # Disambiguate DST transitions by converting to UTC and back
    utc = dt.astimezone(timezone.utc)
    return utc.astimezone(tz)


def ytv_publish_at(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def _template_provenance_gate(project_dir) -> tuple[bool, str | None, str | None, list[str]]:
    """Fail-closed gate for templated projects: bind the claim to template provenance.

    Returns (ok, content_hash, template_id, reasons). Non-templated projects
    (no template_provenance.json) always pass.
    """
    prov_path = project_dir / "template_provenance.json"
    if not prov_path.is_file():
        return True, None, None, []
    prov = template_provenance.verify_project_provenance(project_dir)
    if not prov["ok"]:
        return False, None, prov.get("template_id"), prov["reasons"]
    # Production activation is gated on review approval: a templated project
    # whose package has not been approved must not be scheduled.
    template_id = prov.get("template_id")
    if template_id:
        try:
            catalog = template_provenance.load_catalog()
        except FileNotFoundError:
            catalog = {"packages": []}
        pkg = template_provenance.get_package(catalog, template_id)
        if pkg is None:
            return False, None, template_id, [
                f"template package {template_id!r} not found in catalog; scheduling blocked"
            ]
        if pkg.get("review_status", "pending") != "approved":
            return False, None, template_id, [
                f"package {template_id} review_status is '{pkg.get('review_status', 'pending')}', not 'approved'; production activation is blocked"
            ]
    content_hash = None
    try:
        content_hash = json.loads(prov_path.read_text(encoding="utf-8")).get("content_instance_sha256")
    except Exception:
        content_hash = None
    return True, content_hash, template_id, []

def main():
    parser = argparse.ArgumentParser(description="Same-day native scheduler for queued slots")
    parser.add_argument("--date", help="Override local date YYYY-MM-DD (default today)")
    parser.add_argument(
        "--hold-platform",
        action="append",
        default=[],
        dest="hold_platforms_list",
        help="Hold (pause/skip) publishing to specific platform (e.g. ig, fb, tiktok, ytb). Can be repeated.",
    )
    parser.add_argument(
        "--hold-platforms",
        type=str,
        default="",
        help="Comma-separated platforms to hold (e.g. 'ig,fb,tiktok,ytb')",
    )
    parser.add_argument("--hold-ig", action="store_true", help="Hold Instagram publishing")
    parser.add_argument("--hold-fb", action="store_true", help="Hold Facebook publishing")
    parser.add_argument("--hold-tiktok", action="store_true", help="Hold TikTok publishing")
    parser.add_argument("--hold-ytb", action="store_true", help="Hold YouTube publishing")
    parser.add_argument(
        "--enabled-platforms",
        type=str,
        default="",
        help="Comma or space separated platforms to enable (e.g. 'ytb' or 'youtube,instagram')",
    )
    parser.add_argument(
        "--enable-platform",
        action="append",
        default=[],
        dest="enabled_platforms_list",
        help="Enable a specific platform (e.g. ytb, ig, fb, tiktok). Can be repeated.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run shadow/dry-run schedule simulation without calling remote upload APIs",
    )
    args = parser.parse_args()

    cli_held: list[str] = list(args.hold_platforms_list)
    if args.hold_platforms:
        cli_held.append(args.hold_platforms)
    if args.hold_ig:
        cli_held.append("instagram")
    if args.hold_fb:
        cli_held.append("facebook")
    if args.hold_tiktok:
        cli_held.append("tiktok")
    if args.hold_ytb:
        cli_held.append("youtube")

    cli_enabled: list[str] = list(args.enabled_platforms_list)
    if args.enabled_platforms:
        cli_enabled.append(args.enabled_platforms)
    if not cli_enabled:
        cli_enabled = None

    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    yt_account = cfg["youtube"]["account"]
    today = (datetime.strptime(args.date,"%Y-%m-%d").date() if args.date else datetime.now(tz).date())
    date = today.isoformat()
    # Only schedule queued projects whose publish_date matches the requested date
    raw_queue = [p for p in cfg.get("active_projects",[]) if isinstance(p,dict) and p.get("publish_date")==date]
    seen_pids = set()
    queue = []
    for p in raw_queue:
        pid = p.get("project_id")
        if pid and pid not in seen_pids:
            seen_pids.add(pid)
            queue.append(p)

    if not queue:
        print(f"No queued projects for {date}")
        return 0
    queue.sort(key=lambda p: p.get("publish_time",""))
    MIN_GAP = timedelta(hours=2)
    now = datetime.now(tz)
    store = PublishStore()
    previous = None
    failed = False
    for q in queue:
        proj = q["project_id"]
        publish_at = make_publish_datetime(today, q["publish_time"], tz)
        if previous and publish_at - previous < MIN_GAP:
            print(f"failed {proj}: slot gap under 2h: {previous.isoformat()} -> {publish_at.isoformat()}")
            failed = True
            continue
        previous = publish_at
        if publish_at <= now + timedelta(minutes=20):
            print(f"SKIPPED {proj}: slot cutoff passed ({publish_at.isoformat()}); retaining without failure")
            continue
        project_dir = ROOT / "projects" / proj
        meta_path = project_dir / "publish_metadata.json"
        if not meta_path.is_file():
            print(f"failed {proj}: missing publish_metadata.json")
            failed = True
            continue
        try:
            topic_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as err:
            print(f"failed {proj}: invalid publish_metadata.json ({err})")
            failed = True
            continue

        meta_status = topic_meta.get("status", "")
        if meta_status in ("published", "scheduled"):
            print(f"SKIPPED {proj}: already {meta_status}")
            continue

        yt_account = cfg.get("youtube", {}).get("account", "primary")
        topic_id = topic_meta.get("id") or proj
        format_type = topic_meta.get("format", "short")
        is_longform = format_type in ("longform", "long", "16:9", "16x9")
        kind = "longform" if is_longform else "short"

        from lib.artifact_paths import resolve_render_path, is_english_locale
        locale = topic_meta.get("locale") or "vi-VN"
        is_us_project = is_english_locale(locale) or topic_meta.get("audience") == "us"

        yt_key = publish_key(date, topic_id, "youtube", kind)
        if hasattr(store, "get"):
            existing_claim = store.get(yt_key)
            if existing_claim and existing_claim.get("status") in ("scheduled", "published"):
                print(f"ALREADY SCHEDULED {proj} on youtube ({kind}) for {existing_claim.get('scheduled_for', date)} ({existing_claim.get('video_url', '')})")
                continue

        # Strict validation gate: Ensure project has passed validation_status.json in project dir
        vstatus_path = project_dir / "validation_status.json"
        if not vstatus_path.is_file():
            print(f"failed {proj}: strict validation status missing ({vstatus_path})")
            failed = True
            continue
        try:
            v_data = json.loads(vstatus_path.read_text(encoding="utf-8"))
            if isinstance(v_data, list) and v_data:
                pass_entry = next(
                    (e for e in reversed(v_data) if isinstance(e, dict) and e.get("status") == "PASS" and e.get("strict_quality_pass")),
                    None
                )
                last_entry = pass_entry if pass_entry else v_data[-1]
            elif isinstance(v_data, dict):
                last_entry = v_data
            else:
                last_entry = {}
            if last_entry.get("status") != "PASS" or not last_entry.get("strict_quality_pass"):
                print(f"failed {proj}: strict validation not passed (status={last_entry.get('status')})")
                failed = True
                continue
        except Exception as err:
            print(f"failed {proj}: error reading validation_status.json ({err})")
            failed = True
            continue

        try:
            from lib.news_release_gate import require_news_evidence
            require_news_evidence(project_dir, metadata=topic_meta)
        except Exception as err:
            print(f"failed {proj}: news evidence gate failed ({err})")
            failed = True
            continue
        meta_valid, meta_errors = validate_metadata(meta_path)
        if not meta_valid:
            print(f"failed {proj}: metadata language or structure validation failed: {meta_errors}")
            failed = True
            continue
        # Template provenance gate: a templated project must be backed by a
        # valid provenance record (approved package, byte-matching compositions,
        # verified captions) before it can be queued/scheduled.
        prov_ok, content_hash, template_id, prov_reasons = _template_provenance_gate(project_dir)
        if not prov_ok:
            print(f"failed {proj}: template provenance invalid ({'; '.join(prov_reasons)})")
            failed = True
            continue
        if is_longform:
            yt_rel = topic_meta.get("yt_longform") or topic_meta.get("longform")
            if not yt_rel:
                rp = resolve_render_path(project_dir, format_type="longform", locale=locale)
                yt_rel = rp.relative_to(project_dir) if rp.is_relative_to(project_dir) else rp
        else:
            yt_rel = topic_meta.get("yt_shorts") or topic_meta.get("short")
            if not yt_rel:
                rp = resolve_render_path(project_dir, format_type="short", locale=locale)
                yt_rel = rp.relative_to(project_dir) if rp.is_relative_to(project_dir) else rp

        # Cryptographic supervisor approval gate for US/English deliverables
        if is_us_project or (project_dir / "approval.json").is_file() or (project_dir / "artifacts" / "claim_ledger.json").is_file():
            approval_file = project_dir / "approval.json"
            if not approval_file.is_file():
                approval_file = project_dir / "artifacts" / "approval.json"
            if not approval_file.is_file():
                print(f"failed {proj}: mandatory approval.json missing for US project")
                failed = True
                continue
            try:
                import hashlib
                from lib.qa_signing import verify_approval_record
                approval_data = json.loads(approval_file.read_text(encoding="utf-8"))
                valid_sig, sig_msg = verify_approval_record(
                    approval_data, proj, project_dir=project_dir, require_manifest=is_us_project
                )
                if not valid_sig:
                    print(f"failed {proj}: cryptographic supervisor signature invalid ({sig_msg})")
                    failed = True
                    continue

                # Verify media hash
                approved_media_sha = approval_data.get("approved_media_sha256") or approval_data.get("media_sha256")
                approved_hashes_list = approval_data.get("approved_media_hashes", [])
                if approved_media_sha and yt_rel:
                    target_vid = project_dir / yt_rel
                    if target_vid.is_file():
                        h = hashlib.sha256()
                        with open(target_vid, "rb") as vf:
                            while chunk := vf.read(65536):
                                h.update(chunk)
                        actual_vid_sha = h.hexdigest()
                        all_allowed = set(approved_hashes_list)
                        if approved_media_sha:
                            all_allowed.add(approved_media_sha)
                        if actual_vid_sha not in all_allowed:
                            print(f"failed {proj}: media SHA-256 mismatch ({actual_vid_sha[:16]}... != {approved_media_sha[:16]}...)")
                            failed = True
                            continue

                # Verify claim ledger hash if ledger exists
                approved_claim_sha = approval_data.get("claim_ledger_sha256")
                ledger_file = project_dir / "artifacts" / "claim_ledger.json"
                if approved_claim_sha and ledger_file.is_file():
                    h_c = hashlib.sha256(ledger_file.read_bytes()).hexdigest()
                    if h_c != approved_claim_sha:
                        print(f"failed {proj}: claim ledger SHA-256 mismatch ({h_c[:16]}... != {approved_claim_sha[:16]}...)")
                        failed = True
                        continue
            except Exception as err:
                print(f"failed {proj}: error verifying cryptographic approval ({err})")
                failed = True
                continue

        if isinstance(yt_rel, dict):
            yt_rel = yt_rel.get("path") or yt_rel.get("file")
        ig_rel = topic_meta.get("ig_reels")
        if isinstance(ig_rel, dict):
            ig_rel = ig_rel.get("path") or ig_rel.get("file") or "renders/final_reels_vi_9x16.mp4"
        ig_account = cfg.get("instagram", {}).get("account_id") or cfg.get("meta", {}).get("ig_account_id")
        scheduled_for = publish_at.isoformat()

        is_dry_run = bool(getattr(args, "dry_run", False) or os.environ.get("SHADOW_ROLLOUT") == "1" or os.environ.get("DRY_RUN") == "1")

        # YT
        if not is_platform_enabled("youtube", cfg=cfg, extra_held=cli_held, extra_enabled=cli_enabled):
            print(f"⏸️ HOLD/DISABLED: Skipping YouTube scheduling for {proj} (not enabled or held by pipeline flag/env)")
        else:
            asset_path = project_dir / yt_rel if yt_rel else None
            if not asset_path or not asset_path.is_file():
                print(f"failed {proj}: missing YouTube asset file {asset_path}")
                failed = True
                continue

            if is_dry_run:
                print(f"SHADOW/DRY-RUN: Simulated YouTube {kind} schedule for {proj} at {scheduled_for} (no store mutations, no network upload)")
                payload = build_youtube_payload(topic_meta, video_path=str(asset_path), publish_at=ytv_publish_at(publish_at))
            else:
                yt_key = None; yt_claimed = False
                if yt_rel and (project_dir / yt_rel).is_file():
                    yt_key, yt_claimed,_ = store.claim(
                        date=date,
                        topic=topic_meta["id"],
                        platform="youtube",
                        account=yt_account,
                        kind=kind,
                        status="scheduling",
                        title=topic_meta["title"],
                        asset_path=project_dir/yt_rel,
                        scheduled_for=scheduled_for,
                        content_hash=content_hash,
                        template_id=template_id,
                    )
                if yt_claimed:
                    max_yt_attempts = 3
                    for yt_attempt in range(1, max_yt_attempts + 1):
                        try:
                            payload = build_youtube_payload(topic_meta, video_path=str(project_dir/yt_rel), publish_at=ytv_publish_at(publish_at))
                            r = YoutubePublisher().execute(payload)
                            if r.success:
                                store.mark_scheduled(yt_key, video_id=r.data.get("video_id"), video_url=r.data.get("video_url"), scheduled_for=scheduled_for)
                                print(f"YT scheduled {proj} {scheduled_for}")
                                break
                            else:
                                print(f"YT attempt {yt_attempt}/{max_yt_attempts} failed {proj}: {r.error}")
                                if yt_attempt < max_yt_attempts:
                                    time.sleep(5 * yt_attempt)
                                else:
                                    store.mark_failed(yt_key, r.error)
                                    failed = True
                        except Exception as e:
                            print(f"YT attempt {yt_attempt}/{max_yt_attempts} error {proj}: {e}")
                            if yt_attempt < max_yt_attempts:
                                time.sleep(5 * yt_attempt)
                            else:
                                store.mark_failed(yt_key, str(e))
                                failed = True

        # Schedule Instagram Reels
        if is_us_project and os.environ.get("ENABLE_US_INSTAGRAM") != "1" and "instagram" not in (cli_enabled or []):
            print(f"⏸️ US_MIGRATION_HOLD: Skipping Instagram scheduling for US project {proj} (YouTube-only during US migration phase)")
        elif not is_platform_enabled("instagram", cfg=cfg, extra_held=cli_held, extra_enabled=cli_enabled):
            print(f"⏸️ HOLD/DISABLED: Skipping Instagram scheduling for {proj} (not enabled or held by pipeline flag/env)")
        elif ig_account and ig_rel and (project_dir / ig_rel).is_file():
            if is_dry_run:
                print(f"SHADOW/DRY-RUN: Simulated Instagram Reels schedule for {proj} at {scheduled_for} (no store mutations)")
            else:
                ig_key, ig_claimed,_ = store.claim(
                    date=date,
                    topic=topic_meta["id"],
                    platform="instagram",
                    account=ig_account,
                    kind="reels",
                    status="scheduling",
                    title=topic_meta["title"],
                    asset_path=project_dir/ig_rel,
                    scheduled_for=scheduled_for,
                    content_hash=content_hash,
                    template_id=template_id,
                )
                if ig_claimed:
                    print(f"SCHEDULED: Instagram {date} {topic_meta['id']} {ig_key}")
                else:
                    print(f"SKIP: Instagram {date} {topic_meta['id']} (already claimed)")
        else:
            print(f"SKIP: Instagram {date} {topic_meta['id']} (missing asset or account)")

        time.sleep(1)
    if failed:
        sys.exit(1)
    return 0

if __name__ == "__main__": raise SystemExit(main())
