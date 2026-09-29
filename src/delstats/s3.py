from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .config import DelSourceConfig
from .http import DelHttpClient, DelHttpError


@dataclass(frozen=True)
class S3Object:
    key: str
    last_modified: str | None = None
    etag: str | None = None
    size: int | None = None


def _text(element: ET.Element | None, default: str | None = None) -> str | None:
    return element.text if element is not None else default


def parse_list_objects_xml(xml_text: str) -> tuple[list[S3Object], bool, str | None]:
    """Parse an S3 ListObjects (v1) response.

    Returns (objects, is_truncated, next_marker). Some S3 implementations omit
    NextMarker when no delimiter is used; in that case the final returned key is
    a valid marker for the next request.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DelHttpError("Could not parse S3 bucket listing XML") from exc

    # S3 XML normally uses a default namespace. Strip it from every element so
    # this parser also works with namespace-free test fixtures/proxies.
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    objects: list[S3Object] = []
    for content in root.findall("Contents"):
        key = _text(content.find("Key"))
        if not key:
            continue
        size_text = _text(content.find("Size"))
        objects.append(
            S3Object(
                key=key,
                last_modified=_text(content.find("LastModified")),
                etag=(_text(content.find("ETag")) or "").strip('"') or None,
                size=int(size_text) if size_text and size_text.isdigit() else None,
            )
        )

    is_truncated = (_text(root.find("IsTruncated"), "false") or "false").lower() == "true"
    next_marker = _text(root.find("NextMarker"))
    if is_truncated and not next_marker and objects:
        next_marker = objects[-1].key

    return objects, is_truncated, next_marker


class PublicS3Bucket:
    def __init__(
        self,
        client: DelHttpClient | None = None,
        config: DelSourceConfig | None = None,
    ) -> None:
        self.client = client or DelHttpClient()
        self.config = config or DelSourceConfig()

    def list_objects(self, prefix: str, *, max_keys: int = 1000) -> list[S3Object]:
        """List all public objects under prefix using ListObjects v1 pagination."""
        marker: str | None = None
        found: list[S3Object] = []

        while True:
            params: dict[str, str | int] = {
                "prefix": prefix,
                "max-keys": max_keys,
            }
            if marker:
                params["marker"] = marker

            response = self.client.get(self.config.bucket_url, params=params)
            if response.status_code != 200:
                raise DelHttpError(
                    f"S3 listing returned HTTP {response.status_code} for prefix {prefix!r}"
                )

            objects, truncated, next_marker = parse_list_objects_xml(response.text)
            found.extend(objects)

            if not truncated:
                break
            if not next_marker or next_marker == marker:
                raise DelHttpError(
                    f"S3 listing for {prefix!r} is truncated but did not provide a usable marker"
                )
            marker = next_marker

        return found
