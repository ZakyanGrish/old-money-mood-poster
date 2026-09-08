# content/queue.json

The posting queue for **Old Money Mood only**. Each cron run of the workflow posts
the **first item that is due and not yet posted**, then commits the file back with
`posted_at` filled in. Keep the queue topped up; cadence is set by the cron schedule
in `.github/workflows/post.yml`, not by this file.

## Item schema

```json
{
  "id": "2026-02-01-rules",
  "type": "reel",
  "media_url": "https://<your-r2-domain>/rules.mp4",
  "caption": "The 5 rules old money lives by.\n\nSave this.\n\n#oldmoneyaesthetic #quietluxury #oldmoneymood",
  "not_before": "2026-02-01T17:00:00Z",
  "posted_at": null,
  "result_id": null
}
```

| field | required | notes |
|---|---|---|
| `id` | yes | any unique string |
| `type` | yes | `reel` \| `image` \| `carousel` \| `story` |
| `media_url` | reel/image/story | public HTTPS URL. Images JPEG; video MP4/MOV. |
| `media_urls` | carousel | array of 2–10 image URLs |
| `caption` | optional | ignored for `story` |
| `not_before` | optional | ISO-8601 UTC. Item won't post before this time. |
| `posted_at` | auto | leave `null`; the runner sets it |
| `result_id` | auto | published media id, set by the runner |

## Example with several queued

```json
[
  { "id": "d1", "type": "reel",  "media_url": "https://cdn.example/r1.mp4", "caption": "…", "posted_at": null, "result_id": null },
  { "id": "d2", "type": "image", "media_url": "https://cdn.example/p1.jpg", "caption": "…", "posted_at": null, "result_id": null },
  { "id": "d3", "type": "story", "media_url": "https://cdn.example/s1.jpg", "posted_at": null, "result_id": null }
]
```
