"""Turns a recording's link into something the hub can play. Videos are streamed by the service that hosts them
(Vimeo, YouTube, Loom, Wistia, Bunny Stream, Google Drive, or a GoHighLevel / direct .mp4 file); the hub only embeds
their player. The embed address is always rebuilt from the video's id, never copied from the pasted link, so a
pasted link can't smuggle anything into the page."""
import re
from urllib.parse import parse_qs, quote, urlparse

PROVIDERS = {
    "vimeo": "Vimeo", "youtube": "YouTube", "loom": "Loom", "wistia": "Wistia", "bunny": "Bunny Stream",
    "gdrive": "Google Drive", "file": "Video file", "link": "Link",
}
VIDEO_EXT = (".mp4", ".webm", ".m4v", ".mov")


class BadLink(ValueError):
    pass


def _host(u) -> str:
    return (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")


def parse(raw: str) -> dict:
    """{"provider", "provider_name", "kind": iframe | video | link, "embed": url to play, "url": the cleaned link}."""
    link = (raw or "").strip()
    if not link:
        raise BadLink("Paste the video link.")
    link = link.replace(" ", "%20")  # file names copied with spaces in them
    if re.match(r"^http://", link, re.I):
        link = "https://" + link[7:]  # the hub is https: an http video would be blocked by the browser
    elif not re.match(r"^https://", link, re.I):
        link = "https://" + link
    if len(link) > 1000 or re.search(r"\s", link):
        raise BadLink("That doesn't look like a video link.")
    try:
        u = urlparse(link)
        host = _host(u)
        u.port  # raises on a malformed port
    except ValueError:
        raise BadLink("That doesn't look like a video link. Copy the link from the video's share button.")
    if u.scheme.lower() != "https" or not host or "." not in host or "@" in u.netloc:
        raise BadLink("Use the video's full https:// link.")
    path = u.path or "/"
    q = parse_qs(u.query)
    out = lambda provider, kind, embed: {"provider": provider, "provider_name": PROVIDERS[provider], "kind": kind,  # noqa: E731
                                         "embed": embed, "url": link}

    # Vimeo: vimeo.com/123, vimeo.com/123/abcdef (unlisted), vimeo.com/channels/x/123, player.vimeo.com/video/123?h=abcdef
    if host in ("vimeo.com", "player.vimeo.com") or host.endswith(".vimeo.com"):
        if re.match(r"^/(?:showcase|album)/\d+/?$", path):
            return out("link", "link", link)  # a showcase or album is a page of videos, not one video
        ev = re.match(r"^/event/(\d{4,12})", path)
        if ev:  # a Vimeo live event and its replay
            return out("vimeo", "iframe", f"https://vimeo.com/event/{ev.group(1)}/embed")
        m = re.search(r"(?:^|/)(?:video/)?(\d{5,12})(?:/([0-9a-f]{6,20}))?/?$", path)
        if m:
            vid, h = m.group(1), m.group(2) or (q.get("h") or [""])[0]
            h = h if re.fullmatch(r"[0-9a-f]{6,20}", h or "") else ""
            return out("vimeo", "iframe", f"https://player.vimeo.com/video/{vid}?{'h=' + h + '&' if h else ''}title=0&byline=0&portrait=0&dnt=1")
    # YouTube: watch?v=, youtu.be/, /embed/, /shorts/, /live/
    if host in ("youtube.com", "youtu.be", "youtube-nocookie.com", "music.youtube.com"):
        vid = ""
        playlist = (q.get("list") or [""])[0]
        if path in ("/embed/videoseries", "/playlist") and re.fullmatch(r"[A-Za-z0-9_-]{10,64}", playlist):
            return out("youtube", "iframe", f"https://www.youtube-nocookie.com/embed/videoseries?list={playlist}&rel=0&modestbranding=1")
        if host == "youtu.be":
            vid = path.strip("/").split("/")[0]
        elif path == "/watch":
            vid = (q.get("v") or [""])[0]
        else:
            m = re.match(r"^/(?:embed|shorts|live|v)/([^/?#]+)", path)
            vid = m.group(1) if m and m.group(1) != "videoseries" else ""
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
            return out("youtube", "iframe", f"https://www.youtube-nocookie.com/embed/{vid}?rel=0&modestbranding=1")
    # Loom: loom.com/share/<32 hex> or /embed/<32 hex>
    if host == "loom.com":
        m = re.match(r"^/(?:share|embed)/([0-9a-f]{32})", path)
        if m:
            return out("loom", "iframe", f"https://www.loom.com/embed/{m.group(1)}")
    # Wistia: <account>.wistia.com/medias/<id>, fast.wistia.net/embed/iframe/<id>, wi.st/medias/<id>
    if host.endswith("wistia.com") or host.endswith("wistia.net") or host == "wi.st":
        m = re.search(r"/(?:medias|iframe)/([a-z0-9]{10})(?:/|$)", path)
        if m:
            return out("wistia", "iframe", f"https://fast.wistia.net/embed/iframe/{m.group(1)}")
    # Bunny Stream: iframe.mediadelivery.net/embed|play/<library>/<video guid>
    if host in ("iframe.mediadelivery.net", "player.mediadelivery.net"):
        m = re.match(r"^/(?:embed|play)/(\d{1,10})/([0-9a-f-]{36})", path)
        if m:
            return out("bunny", "iframe", f"https://iframe.mediadelivery.net/embed/{m.group(1)}/{m.group(2)}?autoplay=false&preload=true")
    # Google Drive: drive.google.com/file/d/<id>/view → /preview
    if host == "drive.google.com":
        m = re.match(r"^/file/d/([A-Za-z0-9_-]{10,})", path)
        if m:
            return out("gdrive", "iframe", f"https://drive.google.com/file/d/{m.group(1)}/preview")
    # A video file (GoHighLevel media library, S3, Bunny storage …) plays in the browser's own player
    if path.lower().endswith(VIDEO_EXT):
        clean = f"https://{u.netloc}{quote(path, safe='/%:@-._~!$&()*+,;=')}" + (f"?{u.query}" if u.query else "")
        return out("file", "video", clean)
    # Anything else (a GoHighLevel course page, a Zoom cloud recording, a Drive folder …) opens in a new tab
    return out("link", "link", link)
