#!/usr/bin/env python3
"""
Backcountry Chalet - Facebook + Instagram auto-poster.

Publishes posts from posts.json to the @thebackcountrychalet Facebook Page and
Instagram Business account using the Meta Graph API.

Runs inside GitHub Actions. Reads configuration from environment variables:

  ACCESS_TOKEN      System User long-lived token. Needs pages_manage_posts (FB)
                    and instagram_content_publish + instagram_basic (IG).
                    (IG_ACCESS_TOKEN is also accepted for backward compatibility.)
  FB_PAGE_ID        Facebook Page ID. If set, the post is published to Facebook.
  IG_USER_ID        Instagram Business account ID. If set, the post is published to Instagram.
  IMAGE_BASE_URL    Public base URL for images (must end with "/"). Optional - if unset,
                    it is built from GITHUB_REPOSITORY/GITHUB_REF_NAME so images resolve
                    to raw.githubusercontent.com/<owner>/<repo>/<branch>/bcc-ig-autopost/
  GRAPH_VERSION     Graph API version. Default v21.0.
  POST_ID           If set, force-publish only that post id now (manual test).
  CHECK_ONLY        "true" -> validate token/IDs only, publish nothing.

At least one of FB_PAGE_ID / IG_USER_ID must be set.
With no POST_ID: publishes every post whose date == today (America/Los_Angeles).
Exit code is non-zero on any failure so the Actions run shows red.

No third-party dependencies - standard library only.
"""

import os
import sys
import json
import time
import datetime
import urllib.parse
import urllib.request
import urllib.error

GRAPH = "https://graph.facebook.com/" + os.environ.get("GRAPH_VERSION", "v21.0")
HERE = os.path.dirname(os.path.abspath(__file__))
POSTS_PATH = os.path.join(HERE, "posts.json")


def graph(method, path, params):
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


def image_base_url():
    base = os.environ.get("IMAGE_BASE_URL", "").strip()
    if base:
        return base if base.endswith("/") else base + "/"
    repo = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo"
    ref = os.environ.get("GITHUB_REF_NAME", "main") or "main"
    if not repo:
        raise RuntimeError("IMAGE_BASE_URL not set and GITHUB_REPOSITORY unavailable.")
    return f"https://raw.githubusercontent.com/{repo}/{ref}/bcc-ig-autopost/"


def resolve_image(base, image_field):
    # image_field is like "images/post-01.jpg" (relative to bcc-ig-autopost/)
    return urllib.parse.urljoin(base, image_field.lstrip("/"))


def post_to_facebook(page_id, token, image_url, caption):
    res = graph("POST", f"{page_id}/photos", {
        "url": image_url,
        "caption": caption,
        "access_token": token,
    })
    return res.get("post_id") or res.get("id")


def post_to_instagram(ig_user_id, token, image_url, caption):
    # Step 1: create media container
    container = graph("POST", f"{ig_user_id}/media", {
        "image_url": image_url,
        "caption": caption,
        "access_token": token,
    })
    creation_id = container["id"]

    # Step 2: poll until the container finishes processing
    for _ in range(20):
        status = graph("GET", creation_id, {
            "fields": "status_code,status",
            "access_token": token,
        })
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"IG container {creation_id} processing error: {status}")
        time.sleep(3)
    else:
        raise RuntimeError(f"IG container {creation_id} not ready after polling.")

    # Step 3: publish
    published = graph("POST", f"{ig_user_id}/media_publish", {
        "creation_id": creation_id,
        "access_token": token,
    })
    return published.get("id")


def load_posts():
    with open(POSTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("posts", [])


def main():
    token = (os.environ.get("ACCESS_TOKEN") or os.environ.get("IG_ACCESS_TOKEN") or "").strip().strip('"').strip("'").strip()
    fb_page_id = os.environ.get("FB_PAGE_ID", "").strip()
    ig_user_id = os.environ.get("IG_USER_ID", "").strip()
    post_id = os.environ.get("POST_ID", "").strip()
    check_only = os.environ.get("CHECK_ONLY", "").strip().lower() == "true"

    if not token:
        sys.exit("ERROR: ACCESS_TOKEN (or IG_ACCESS_TOKEN) is not set.")
    if not fb_page_id and not ig_user_id:
        sys.exit("ERROR: set at least one of FB_PAGE_ID / IG_USER_ID.")

    # Fetch the Page access token (required to publish to the Page) and auto-derive the
    # linked Instagram Business account - both in one call.
    fb_token = token
    if fb_page_id:
        try:
            pg = graph("GET", fb_page_id, {
                "fields": "access_token,instagram_business_account{id,username}",
                "access_token": token,
            })
            if pg.get("access_token"):
                fb_token = pg["access_token"]
                print("Using Page access token for Facebook.")
            if not ig_user_id:
                iba = (pg or {}).get("instagram_business_account") or {}
                if iba.get("id"):
                    ig_user_id = iba["id"]
                    print(f"Derived IG account from Page: @{iba.get('username','?')} ({ig_user_id})")
                else:
                    print("No Instagram Business account is linked to this Page; Instagram will be skipped.")
        except Exception as e:
            print(f"Could not fetch Page token / IG account: {e}")

    targets = []
    if fb_page_id:
        targets.append("Facebook")
    if ig_user_id:
        targets.append("Instagram")
    print(f"Channels enabled: {', '.join(targets)}")

    if check_only:
        me = graph("GET", "me", {"access_token": token})
        print(f"Token OK. App user: {me.get('name', me)}")
        if fb_page_id:
            page = graph("GET", fb_page_id, {"fields": "name", "access_token": token})
            print(f"Facebook Page OK: {page.get('name', fb_page_id)}")
        if ig_user_id:
            ig = graph("GET", ig_user_id, {"fields": "username", "access_token": token})
            print(f"Instagram account OK: @{ig.get('username', ig_user_id)}")
        print("CHECK_ONLY: nothing published.")
        return

    posts = load_posts()
    base = image_base_url()

    if post_id:
        due = [p for p in posts if str(p.get("id")) == post_id]
        if not due:
            sys.exit(f"ERROR: POST_ID {post_id} not found in posts.json.")
    else:
        today = today_la()
        due = [p for p in posts if p.get("date") == today]
        print(f"Today (LA): {today}")

    if not due:
        print("No post scheduled for today. Nothing to do.")
        return

    failures = 0
    for p in due:
        pid = p.get("id")
        image_url = resolve_image(base, p["image"])
        caption = p["caption"]
        print(f"\n--- Post #{pid} ({p.get('date')}) ---")
        print(f"Image: {image_url}")

        if fb_page_id:
            try:
                fb_id = post_to_facebook(fb_page_id, fb_token, image_url, caption)
                print(f"  Facebook: published ({fb_id})")
            except Exception as e:
                # Facebook is best-effort: a FB failure (e.g. pages_manage_posts not yet
                # approved on the Meta app) must NOT block the daily Instagram post.
                print(f"  Facebook: SKIPPED (non-fatal) - {e}")

        if ig_user_id:
            try:
                ig_id = post_to_instagram(ig_user_id, token, image_url, caption)
                print(f"  Instagram: published ({ig_id})")
            except Exception as e:
                failures += 1
                print(f"  Instagram: FAILED - {e}")

    if failures:
        sys.exit(f"\n{failures} publish action(s) failed.")
    print("\nAll posts published successfully.")


if __name__ == "__main__":
    main()
