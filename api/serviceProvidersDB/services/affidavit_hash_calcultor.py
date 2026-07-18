import hashlib


def calculate_sha256(file):
    """
    Calculates the SHA-256 hash of an uploaded file.
    """

    sha256 = hashlib.sha256()

    for chunk in file.chunks():
        sha256.update(chunk)

    file.seek(0)

    return sha256.hexdigest()