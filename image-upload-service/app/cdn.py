"""CDN URL generation.

For production: set CLOUDFRONT_DOMAIN, CLOUDFRONT_KEY_PAIR_ID, and
CLOUDFRONT_PRIVATE_KEY_PATH to enable CloudFront signed URLs.

For LocalStack / local dev: leave those vars unset and the service falls back
to S3 pre-signed GET URLs automatically.
"""

import datetime
from typing import Literal

from app.config import (
    CLOUDFRONT_DOMAIN,
    CLOUDFRONT_KEY_PAIR_ID,
    CLOUDFRONT_PRIVATE_KEY_PATH,
    PRESIGN_EXPIRY_SECONDS,
)
from app import s3


def _load_cf_signer():
    if not (CLOUDFRONT_DOMAIN and CLOUDFRONT_KEY_PAIR_ID and CLOUDFRONT_PRIVATE_KEY_PATH):
        return None

    from botocore.signers import CloudFrontSigner
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    with open(CLOUDFRONT_PRIVATE_KEY_PATH, "rb") as fh:
        private_key = load_pem_private_key(fh.read(), password=None)

    def _rsa_signer(message: bytes) -> bytes:
        # CloudFront requires RSA-SHA1
        return private_key.sign(message, padding.PKCS1v15(), hashes.SHA1())

    return CloudFrontSigner(CLOUDFRONT_KEY_PAIR_ID, _rsa_signer)


def get_view_url(s3_key: str) -> tuple[str, Literal["cloudfront", "s3"]]:
    """Return (signed_url, via) for the given S3 key.

    'via' tells the caller whether the URL goes through CloudFront or S3 directly.
    """
    signer = _load_cf_signer()
    if signer:
        base_url = f"https://{CLOUDFRONT_DOMAIN}/{s3_key}"
        expiry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            seconds=PRESIGN_EXPIRY_SECONDS
        )
        return signer.generate_presigned_url(base_url, date_less_than=expiry), "cloudfront"

    result = s3.generate_download_url(s3_key)
    return result["url"], "s3"
