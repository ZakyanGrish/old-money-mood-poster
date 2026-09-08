# Social Media Poster

Scripted posting to **Instagram Business**, **Facebook Pages**, and (later) **TikTok Business**
via the official Meta Graph API. No third-party service.

```
post.py                  CLI entry point
smposter/meta.py         Graph API wrapper (image / Reel / carousel / Page post)
smposter/config.py       .env + accounts.json loader
scripts/meta_get_ids.py  discover your Page IDs + IG account IDs
scripts/exchange_token.py short-lived token -> 60-day token
```

## Prerequisites

- Instagram account is **Business or Creator** and **linked to a Facebook Page**
  (IG app → Settings → Account type and tools → Switch to professional; then link the Page).
- You have a Facebook account with an **admin role on that Page**.

## Instagram setup (≈15 min, no App Review if you own the accounts)

### 1. Create a Meta app
1. Go to <https://developers.facebook.com/apps/> → **Create app**.
2. Use case: **Other** → type: **Business** → name it, create.
3. In the app dashboard, **Add product → "Instagram" → "Instagram API setup with Facebook Login"** (the flow for Business accounts linked to a Page).
4. **App settings → Basic**: copy **App ID** and **App Secret** into `.env`.

### 2. Add your account as a user of the app (this is what avoids App Review)
- **App roles → Roles**: add your Facebook profile as **Administrator** (or Tester) and accept the invite.
- Because your IG accounts are administered by a user with a role on the app, `instagram_content_publish` works in **Development mode** — no review submission needed. App Review is only required to post for accounts you don't control.

### 3. Get a token
1. **Tools → Graph API Explorer**.
2. Top right: select your app. Click **Generate Access Token**.
3. Add these permissions, then generate:
   `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
   `business_management`
4. Copy the token — it's short-lived (~1 hour).

### 4. Make the token last 60 days
```bash
cp .env.example .env      # then fill META_APP_ID + META_APP_SECRET
python scripts/exchange_token.py <paste-short-lived-token>
```
Put the printed long-lived token into `.env` as `META_ACCESS_TOKEN`.

> For a **never-expiring** token later: business.facebook.com → Business Settings →
> Users → **System Users** → add one → assign your app + Page with full control →
> **Generate token** with the same scopes. Swap it into `.env`.

### 5. Discover your IDs and write accounts.json
```bash
python scripts/meta_get_ids.py
```
Copy the printed skeleton into `accounts.json` (gitignored). One entry per account:
```json
{
  "my-brand": { "ig_user_id": "17841...", "fb_page_id": "1023...", "token_env": null }
}
```
`token_env: null` → uses `META_ACCESS_TOKEN`. Set it to another env var name to give an account its own token.

### 6. Post
```bash
python post.py --account my-brand --check                 # quota sanity check
python post.py --account my-brand --dry-run --image x      # config check, no post
python post.py --account my-brand --image  https://.../photo.jpg   --caption "Hello 👋"
python post.py --account my-brand --reel   https://.../clip.mp4    --caption "New reel"
python post.py --account my-brand --carousel https://.../1.jpg https://.../2.jpg --caption "Set"
```

## Media hosting

Instagram **pulls media from a public HTTPS URL** — you can't upload bytes directly.
Options: an S3/R2 bucket, Cloudinary, or any static host. Images must be **JPEG**,
≤ 8 MB; Reels are MP4/MOV, ≤ 1 GB, 3–90 s.

## Limits

- 100 IG API posts per account per rolling 24 h (`--check` shows usage).
- ~200 Graph calls/hour/user baseline.

## Roadmap

- [ ] Facebook Page posting wired into `post.py` (`smposter/meta.py` already has `page_post_*`)
- [ ] TikTok Content Posting API (`video.publish`) — needs a separate TikTok app + audit
- [ ] optional S3/R2 upload helper so you can pass local files
