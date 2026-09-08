# APasz Hub

A small FastHTML public link hub

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/)

## Development

```bash
uv sync --all-groups
uv run python main.py
```

The development server listens on `http://127.0.0.1:5001` by default
Set `PORT` to override the port

Run the checks with:

```bash
uv run ruff check .
uv run basedpyright
uv run python -m unittest discover -s tests -v
```

## Link cards

Edit `src/apasz_hub/link_cards.json` to update homepage destinations
The file is validated and reloaded for every homepage request, so valid changes don't need a server restart

Each card requires `title`, `href`, `tier`, and `icon`
`tier` is `featured`, `standard`, or `utility`
Optional fields are `description`, `border_hover`, `border_static`, `icon_static`, `icon_hover`, `metadata`, `icon_scale`, `schema`, `opens_in_new_tab`, `copy_to_clipboard`, and `copy_text`

Featured cards require `metadata`
`icon_scale` is a positive integer and defaults to `100`;
links open in a new tab by default
`schema` defaults to `normal`; `mail` requires a non-empty `mailto:` destination
and `github` requires a canonical `https://github.com/<login>` profile URL
Clipboard actions require `copy_to_clipboard: true` and a non-empty `copy_text`; they can be used with any card tier or schema

GitHub cards refresh their public repository count in a background task when the
server starts and then every 18 hours. Homepage visits only use the last
refreshed value. Configured metadata is used until the first successful refresh;
the last successful value remains visible through a temporary GitHub failure.

For deployment, `APASZ_HUB_LINK_CARDS_PATH` can select another card file
Use an absolute path in persistent writable storage; it is also reloaded per request

## Production

`main.py` is a loopback-only development server with live reload
Run the production entry point instead:

```bash
PORT=5001 APASZ_HUB_HOST=127.0.0.1 uv run python -m apasz_hub.production
```

Production disables reload, proxy-header trust, and Uvicorn's identifying header
It binds to loopback by default;
set `APASZ_HUB_HOST=0.0.0.0` only when a container platform requires it

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
