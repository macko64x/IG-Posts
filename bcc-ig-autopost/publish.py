#!/usr/bin/env python3
"""
Backcountry Chalet — Instagram auto-poster.

Publishes posts from posts.json to the @thebackcountrychalet Instagram account
using the Meta Graph API (Instagram Content Publishing).

Runs inside GitHub Actions. Reads configuration from environment variables:

  IG_USER_ID        Instagram Business account ID (e.g. 17841439102452199)   [required]
  IG_ACCESS_TOKEN   System User long-lived token with instagram_content_publish [required]
  IMAGE_BASE_URL    Public base URL for images. Optional — if unset, it is built
                    from the GitHub repo so images resolve to raw.githubusercontent.com.
  POST_ID           If set, force-publish only that post id now (manual test).
  CHECK_ONLY        "true" -> only validate token/account, publish nothing.

Behavior with no POST_ID: publishes every post whose date == today (America/Los_Angeles).
Exit code is non-zero on any failure so the Actions run shows red.
"""

import os
import sys
import json
import time
import datetime
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com/v21.0"


def log(msg):
    print(msg, flush=True)


def api(method, path, params):
    """Minimal Graph API call using urllib (no third-party deps needed)."""
    url = f"{GRAPH}/{path}"
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        url = url + "?" + data.decode()
        req = urllib.request.Request(url, method="GET")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Graph API {method} {path} failed: HTTP {e.code} {body}")


def today_la():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        # Fallback: assume runner is UTC, shift -8h as a rough PT approximation.
        return (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).date().isoformat()


def image_base():
    base = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
    if base:
        return base
    repo = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo"
    ref = os.environ.get("GITHUB_REF_NAME", "main")
    if not repo:
        raise RuntimeError("IMAGE_BASE_URL not set and GITHUB_REPOSITORY unavailable.")
    return f"https://raw.githubusercontent.com/{repo}/{ref}"


def publish_one(ig_user, token, base, post):
    img_url = f"{base}/{post['image']}"
    log(f"\n[post #{post['id']} · {post['date']}] image: {img_url}")

    # 1) create media container
    res = api("POST", f"{ig_user}/media", {
        "image_url": img_url,
        "caption": post["caption"],
        "access_token": token,
    })
    creation_id = res.get("id")
    if not creation_id:
        raise RuntimeError(f"No creation id returned: {res}")
    log(f"  container: {creation_id}")

    # 2) wait until the container is FINISHED (images are usually instant)
    for _ in range(20):
        st = api("GET", creation_id, {"fields": "status_code,status", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"Container errored: {st}")
        time.sleep(3)

    # 3) publish
    pub = api("POST", f"{ig_user}/media_publish", {
        "creation_id": creation_id,
        "access_token": token,
    })
    media_id = pub.get("id")
    if not media_id:
        raise RuntimeError(f"Publish failed: {pub}")
    log(f"  PUBLISHED · media id {media_id}")
    return media_id


def main():
    ig_user = os.environ.get("IG_USER_ID")
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not ig_user or not token:
        log("ERROR: IG_USER_ID and IG_ACCESS_TOKEN must be set (GitHub secrets).")
        sys.exit(2)

    # Validate token + account first (cheap, confirms wiring).
    me = api("GET", ig_user, {"fields": "username,followers_count,media_count", "access_token": token})
    log(f"Account OK: @{me.get('username')} · {me.get('followers_count')} followers · {me.get('media_count')} posts")

    if os.environ.get("CHECK_ONLY", "").lower() == "true":
        log("CHECK_ONLY mode — validation passed, nothing published.")
        return

    posts = json.load(open(os.path.join(os.path.dirname(__file__), "posts.json"), encoding="utf-8"))
    base = image_base()

    post_id = os.environ.get("POST_ID", "").strip()
    if post_id:
        targets = [p for p in posts if str(p["id"]) == post_id]
        if not targets:
            log(f"ERROR: no post with id {post_id}")
            sys.exit(2)
        log(f"Manual run: force-publishing post #{post_id}")
    else:
        today = today_la()
        targets = [p for p in posts if p["date"] == today]
        log(f"Scheduled run for {today}: {len(targets)} post(s) due.")

    if not targets:
        log("Nothing to publish today.")
        return

    failures = 0
    for p in targets:
        try:
            publish_one(ig_user, token, base, p)
        except Exception as e:
            failures += 1
            log(f"  FAILED post #{p['id']}: {e}")

    if failures:
        log(f"\n{failures} post(s) failed.")
        sys.exit(1)
    log("\nDone.")


if __name__ == "__main__":
    main()
