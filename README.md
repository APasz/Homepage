# APasz Hub

A small FastHTML public link hub

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/)

## Development

```bash
uv sync --all-groups
uv run python main.py
```

The development server listens on `http://127.0.0.1:2036` by default
Set `PORT` to override the port

Run the checks with:

```bash
uv run ruff check .
uv run basedpyright
uv run python -m unittest discover -s tests -v
```

## Link cards

Link cards are loaded and validated once when the server starts. After enabling
configuration access, visit `/config` to edit its in-memory draft. **Add Link**
appends a default card, and **Delete** appears on expanded cards; neither change
is live until **Save Links** atomically writes the draft to
`src/apasz_hub/link_cards.json` and publishes it to the homepage. External JSON
changes require a server restart to be picked up.

Each card requires `title`, `href`, `tier`, and `icon`
`tier` is `featured`, `standard`, or `utility`
Optional fields are `description`, `border_hover`, `border_static`, `icon_static`, `icon_hover`, `metadata`, `icon_scale`, `schema`, `opens_in_new_tab`, `copy_to_clipboard`, and `copy_text`

Featured cards require `metadata`
`icon_scale` is a positive integer and defaults to `100`;
links open in a new tab by default
`schema` defaults to `normal`; `mail` requires a `mailto:` destination with an
email address and `github` requires a canonical `https://github.com/<login>`
profile URL
Clipboard actions require `copy_to_clipboard: true` and a non-empty `copy_text`; they can be used with any card tier or schema

The config editor presents a schema-specific destination field: normal cards use
a full URL, GitHub cards use only a username, and email cards use only an email
address. The latter two are converted to their canonical `href` values when
the draft is saved.

## Configuration access

`/config` is closed by default. The public footer deliberately does not link to
it. To enable the single-administrator editor, run this once from the project
root:

```bash
uv run apasz-hub-setup
```

It prompts twice for the configuration password without echoing it, generates
the Argon2id password hash and session secret, and atomically creates a
mode-`600` `.env`. The default browser origin is `https://apasz.com`. For
another deployment, supply its exact external origin, without a path:

```bash
uv run apasz-hub-setup --origin https://example.com
```

The command refuses to touch an existing `.env`. `--replace` deliberately
creates fresh credentials and replaces the entire file, so back up any runtime
settings in it first. [.env.example](.env.example) remains available for a
manual setup.

A partial or invalid access configuration leaves `/config` closed and records a
startup error. The app reads the repository-root `.env` with Pydantic Settings,
independent of the service working directory, and rejects unknown dotenv names,
so typos fail loudly instead of being silently ignored.

Never commit `.env`; it is ignored by Git. A successful login creates a
server-side session with a 30-minute idle lifetime and an eight-hour absolute
lifetime; restarting the application or rotating the session secret invalidates
all sessions.

Cookies are HTTPS-only by default. For a loopback HTTP development server only,
use the explicit local-only option. Never use it in production.

```bash
uv run apasz-hub-setup --origin http://127.0.0.1:2036 --insecure-cookie
```

Every authenticated configuration write verifies both a per-session CSRF token
and the exact configured `Origin`. Login attempts are rate-limited after five
failures in 15 minutes. Login outcomes and explicit configuration save, add,
and delete actions are logged without logging passwords or submitted
configuration data.

## Appearance

Shared interface colours are stored in `src/apasz_hub/theme_colors.json` and
supplied to the site through `/theme.css`. The application validates the file
at startup and serves that published in-memory snapshot. The authenticated
`/config` page previews changes; **Save colours** atomically persists and
publishes a new snapshot. Reset discards unsaved edits. Manual file edits take
effect after a restart, so a malformed edit cannot interrupt public requests.

For deployment, set `THEME_COLORS_PATH` in `.env` to a persistent writable JSON
file rather than the packaged default.

Link-card border and icon colours can be overridden from `/config`. Leave Auto
enabled to inherit the matching shared palette colour; custom overrides persist
with the LinkCard JSON data.

## Open Graph previews

The `/config` page also controls the site name, title, description, and optional
image URL used when the homepage is shared. These values update the standard
description, Open Graph, and X/Twitter metadata together. The canonical URL
continues to come from `PUBLIC_ORIGIN`, so it remains consistent with the public
deployment origin.

The data is stored in `src/apasz_hub/open_graph.json`. For deployment, set
`OPEN_GRAPH_PATH` to a persistent writable JSON file.

## GitHub card metadata

GitHub cards refresh their public repository count in a background task when the
server starts and then every 18 hours. Homepage visits only use the last
refreshed value. Configured metadata is used until the first successful refresh;
the last successful value remains visible through a temporary GitHub failure.

For deployment, set `LINK_CARDS_PATH` in `.env` to an alternate card file.
Use an absolute path in persistent writable storage.

## Production

`main.py` is a loopback-only development server with live reload
Run the production entry point instead:

```bash
PORT=2036 HOST=127.0.0.1 uv run python -m apasz_hub.production
```

Production disables reload and Uvicorn's identifying header. It accepts
forwarded headers only from a loopback Caddy proxy (`127.0.0.1`), so login
rate limiting sees the browser's client address. This deployment assumes the
application port remains loopback-only and is never directly exposed; keep
`HOST=127.0.0.1` when Caddy runs on the same host.

When a TLS proxy or CDN fronts the site, firewall the application port so the
origin cannot be reached directly. Set `PUBLIC_ORIGIN` to the public
HTTPS origin; it remains authoritative for CSRF and origin validation. Do not
derive security decisions from forwarded Host or other request headers. An
identity-aware proxy with MFA and edge rate limiting can provide an additional
admin boundary.

Responses use a restrictive CSP and browser-hardening headers
Card inline styles remain allowed
Unless a cache policy already exists, static `2xx` and
`304` responses get a one-hour, must-revalidate policy
Do not mark assets immutable until filenames are fingerprinted
Configure HSTS at the TLS-terminating proxy or CDN

## Assets

### SVG icons

Add SVGs to `src/apasz_hub/static/icons/`, then crop their canvases with
Inkscape:

The config page automatically lists these SVGs in the LinkCard icon picker.

```bash
uv run python tools/crop_svg_icons.py
```

Pass paths inside that directory to crop selected files
Inkscape is needed only for this development-time asset step

### Profile media

Keep the source animation at `assets/profile/pfp-anim.webp`, then build the 256px animated and reduced-motion WebPs plus a 64px PNG favicon:

```bash
uv run python tools/build_profile_media.py
```

ImageMagick 7 (`magick`) is required only to regenerate these public assets
