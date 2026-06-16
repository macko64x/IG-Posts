# Backcountry Chalet — Instagram auto-poster

Publishes the Q4 2026 content calendar to **@thebackcountrychalet** automatically,
on schedule, with zero clicks — using GitHub Actions + the Meta Graph API.

No server, no PC left on. GitHub runs it.

## How it works

- `posts.json` — the 37 posts (date, caption, image filename).
- `images/` — one photo per post (`post-01.jpg` … `post-37.jpg`).
- `publish.py` — creates the Instagram media container and publishes it.
- `.github/workflows/post.yml` — runs daily; publishes only the post dated that day (Pacific time). Also has a manual "Run workflow" button for testing.

Images are served to Instagram from this repo via `raw.githubusercontent.com`, so **the repo must be Public** (the photos are marketing images; the token is NOT in the repo — it lives in encrypted Secrets).

## One-time setup

1. **Create the repo** on GitHub (Public). Upload everything in this folder
   (drag-and-drop via "Add file → Upload files" is fine — include the `images/` folder
   and the hidden `.github/` folder).

2. **Add two repository secrets** (Settings → Secrets and variables → Actions → New repository secret):
   - `IG_USER_ID` = `17841439102452199`
   - `IG_ACCESS_TOKEN` = your System User token
     (generate it with **expiration: Never** so it survives the whole campaign).

3. **Test it** (no waiting): Actions tab → "Post to Instagram" → **Run workflow**.
   - First, run once with **check_only = true** → confirms the token and account are wired (publishes nothing).
   - Then run with **post_id = 1** → publishes post #1 immediately. That's your live proof.

4. **Leave it.** From then on the daily schedule publishes each post on its date.
   Mon/Wed/Fri, Oct 5 – Dec 30, 2026.

## Editing content

- Change a caption: edit `posts.json` (or regenerate it from the calendar) and commit.
- Swap a photo: replace the matching `images/post-NN.jpg` and commit.

## Notes

- Posting time is set in `post.yml` (`cron: "30 17 * * *"` = 17:30 UTC). Adjust if you want a different hour.
- Instagram requires an image on every post and a public image URL — both handled here.
- If you ever make the repo Private, set an `IMAGE_BASE_URL` secret pointing at a public host (e.g. your qydjgetaway.com path) instead of relying on raw.githubusercontent.com.
