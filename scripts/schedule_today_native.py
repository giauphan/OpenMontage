#!/usr/bin/env python3
"""Native YouTube scheduler with Instagram claims for slot cron.
Filters queued projects by publish_date == --date. Usage: --date YYYY-MM-DD (default today VN).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
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
from tools.publish_store import PublishStore
from tools.publishers.platform_routes import (
    youtube_shorts_title,
    compose_release_metadata,
)
from tools.publishers.youtube_publisher import YoutubePublisher


def build_youtube_payload(topic_meta: dict, video_path: str, publish_at: str | None = None) -> dict:
    """Build unified YouTube Shorts upload payload using compose_release_metadata."""
    # Ensure id/title/desc exist for compose
    payload_meta = dict(topic_meta)
    if "id" not in payload_meta:
        payload_meta["id"] = payload_meta.get("project_id", "news_video")
    rel = compose_release_metadata(payload_meta)
    yt = rel.youtube_payload
    return {
        "video_path": str(video_path),
        "title": yt["title"],
        "description": yt["description"],
        "tags": yt["tags"],
        "privacy_status": "private" if publish_at else "unlisted",
        "publish_at": publish_at,
        "category_id": "28",
    }


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
    queue = [p for p in cfg.get("active_projects",[]) if isinstance(p,dict) and p.get("publish_date")==date]

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
        hh,mm = q["publish_time"].split(":",1)
        publish_at = datetime.combine(today, datetime.strptime(f"{hh}:{mm}","%H:%M").time(), tz)
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
        topic_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        try:
            from lib.news_release_gate import require_news_evidence
            require_news_evidence(project_dir, metadata=topic_meta)
        except Exception as err:
            print(f"failed {proj}: news evidence gate failed ({err})")
            failed = True
            continue
        meta_status = topic_meta.get("status","")
        if meta_status in ("published", "scheduled"):
            print(f"failed {proj}: status '{meta_status}'")
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
        yt_rel = topic_meta.get("yt_shorts")
        if isinstance(yt_rel, dict):
            yt_rel = yt_rel.get("path") or yt_rel.get("file") or "renders/final_reels_vi_9x16.mp4"
        ig_rel = topic_meta.get("ig_reels")
        if isinstance(ig_rel, dict):
            ig_rel = ig_rel.get("path") or ig_rel.get("file") or "renders/final_reels_vi_9x16.mp4"
        ig_account = cfg.get("instagram", {}).get("account_id") or cfg.get("meta", {}).get("ig_account_id")
        scheduled_for = publish_at.isoformat()

        # YT
        if not is_platform_enabled("youtube", cfg=cfg, extra_held=cli_held, extra_enabled=cli_enabled):
            print(f"⏸️ HOLD/DISABLED: Skipping YouTube scheduling for {proj} (not enabled or held by pipeline flag/env)")
        else:
            asset_path = project_dir / yt_rel if yt_rel else None
            if not asset_path or not asset_path.is_file():
                print(f"failed {proj}: missing YouTube asset file {asset_path}")
                failed = True
                continue
            yt_key = None; yt_claimed = False
            if yt_rel and (project_dir / yt_rel).is_file():
                yt_key, yt_claimed,_ = store.claim(
                    date=date,
                    topic=topic_meta["id"],
                    platform="youtube",
                    account=yt_account,
                    kind="short",
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
        if not is_platform_enabled("instagram", cfg=cfg, extra_held=cli_held, extra_enabled=cli_enabled):
            print(f"⏸️ HOLD/DISABLED: Skipping Instagram scheduling for {proj} (not enabled or held by pipeline flag/env)")
        elif ig_account and ig_rel and (project_dir / ig_rel).is_file():
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
