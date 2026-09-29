from dataclasses import dataclass


@dataclass(frozen=True)
class DelSourceConfig:
    """URLs and source conventions used by the DEL/Hokejovy zapis data feed."""

    bucket_name: str = "de.hokejovyzapis.cz"
    s3_endpoint: str = "https://s3.eu-west-1.amazonaws.com"

    @property
    def bucket_url(self) -> str:
        return f"{self.s3_endpoint.rstrip('/')}/{self.bucket_name}"

    def object_url(self, key: str) -> str:
        return f"{self.bucket_url}/{key.lstrip('/')}"
